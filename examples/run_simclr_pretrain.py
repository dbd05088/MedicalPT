import pdb, os
import random
from torch import nn
import numpy as np
import torch
from torch.utils.data import DataLoader
from torchvision import transforms


from examples.DRD import DRD

from medclip_v2.modeling_medclip import MedCLIPVisionModelViTOnly, SuperviseClassifier, MedCLIPModel
from medclip_v2.dataset import ZeroShotImageDataset, SuperviseImageDataset
from medclip_v2.dataset import ZeroShotImageCollator, SuperviseImageCollator
from medclip_v2.losses import SimCLRLoss
from medclip_v2.trainer import Trainer
from medclip_v2.evaluator import Evaluator
from medclip_v2 import constants

# set random seed

seed = 42
random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)
torch.cuda.manual_seed(seed)
os.environ['PYTHONASHSEED'] = str(seed)
os.environ['TOKENIZERS_PARALLELISM']='false'

# set cuda devices
os.environ['CUDA_VISIBLE_DEVICES']='0'
device = "cuda:0" if torch.cuda.is_available() else "cpu"


# set training configurations
train_config = {
    'batch_size': 100,
    'num_epochs': 10,
    'warmup': 0.1, # the first 10% of training steps are used for warm-up
    'lr': 2e-5,
    'weight_decay': 1e-4,
    'eval_batch_size': 256,
    'eval_steps': 1000,
    'save_steps': 1000,
}

# only pretrain on chexpert train data and mimic-cxr data
# do zero-shot training on chexpert-5x200 and iuxray
datalist = [
    'chexpert-train',
    'mimic-cxr-train',
]

transform = transforms.Compose([
                transforms.RandomHorizontalFlip(0.5),
                transforms.RandomAffine(degrees=10, scale=(0.8,1.1), translate=(0.0625,0.0625)),
                transforms.Resize((256, 256)),
                transforms.RandomCrop((constants.IMG_SIZE, constants.IMG_SIZE)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[constants.IMG_MEAN],std=[constants.IMG_STD])],
            )

dataset = DRD(transform)
traindata = dataset.get_D1_train()
val_data = dataset.get_D1_valid()
testdata = dataset.get_D1_test()

# traindata = SuperviseImageDataset(datalist=datalist, imgtransform=transform)
train_collate_fn = SuperviseImageCollator(mode='multiclass')
trainloader = DataLoader(traindata,
    batch_size=train_config['batch_size'],
    collate_fn=train_collate_fn,
    shuffle=True,
    pin_memory=True,
    num_workers=12,
    )

# build medclip model
### Since we only use Vision Encoder, it returns just visual embedding (not passed fc layer)
# model = MedCLIPVisionModelViT
model = MedCLIPModel(vision_cls=MedCLIPVisionModelViTOnly)
model = model.vision_model
model.cuda()

# build evaluator
# val_data = ZeroShotImageDataset(['chexpert-5x200-val'],
#     class_names=constants.CHEXPERT_COMPETITION_TASKS)
# val_collate_fn = ZeroShotImageCollator(mode='multiclass')
val_collate_fn = SuperviseImageCollator(mode='multiclass')
eval_dataloader = DataLoader(val_data,
    batch_size=train_config['eval_batch_size'],
    collate_fn=val_collate_fn,
    shuffle=False,
    pin_memory=True,
    num_workers=4,
    )
medclip_clf = SuperviseClassifier(model, mode='multiclass')
evaluator = Evaluator(
    medclip_clf=medclip_clf,
    eval_dataloader=eval_dataloader,
    mode='multiclass',
)

# build loss models and start training
loss_model = SimCLRLoss(model, train_config['batch_size'])
loss_model.cuda()
train_objectives = [
    (trainloader, loss_model, 1),
]
model_save_path = f'./checkpoints/vision_pretrain'
trainer = Trainer()
trainer.train(
    model,
    train_objectives=train_objectives,
    warmup_ratio=train_config['warmup'],
    epochs=train_config['num_epochs'],
    optimizer_params={'lr':train_config['lr']},
    output_path=model_save_path,
    evaluation_steps=train_config['eval_steps'],
    weight_decay=train_config['weight_decay'],
    save_steps=train_config['save_steps'],
    evaluator=evaluator,
    eval_dataloader=eval_dataloader,
    use_amp=True,
    )
print('done')
