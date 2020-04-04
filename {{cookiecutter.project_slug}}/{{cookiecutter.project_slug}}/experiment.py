import datetime
import os
from os import path

import torch
import pytorch_lightning as pl
from pytorch_lightning import callbacks

from . import net
from .data import instance, loader

class Experiment(pl.LightningModule):

    def __init__(self, config):
        super().__init__()
        self.config = config
        
        self.model = net.model.get_model(**config['model'])

        loss_conf = config['loss']
        loss_cls = net.losses.__dict__[loss_conf['type']]
        self.loss = loss_cls(**loss_conf['kwargs'])
        self._batch_size = None

    @property
    def batch_size(self):
        if self._batch_size is None:
            batch_size = self.config['data']['batch_size']
            if self.trainer.use_dp:
                batch_size *= self.config['trainer']['gpus']
            self._batch_size = batch_size
        return self._batch_size

    def forward(self, x):
        return self.model.forward(x)

    def training_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self(x)

        loss_val = self.loss(y_hat, y)

        if self.trainer.use_dp or self.trainer.use_ddp2:
            loss_val = loss_val.unsqueeze(0)

        return {'loss': loss_val}

    def validation_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self(x)

        loss_val = self.loss(y_hat, y)

        if self.trainer.use_dp or self.trainer.use_ddp2:
            loss_val = loss_val.unsqueeze(0)

        return {'val_loss': loss_val}

    def configure_optimizers(self):
        optim_conf = self.config['optim']
        optim_cls = net.optim.__dict__[optim_conf['type']]
        optimizer = optim_cls(self.parameters(), **optim_conf['kwargs'])

        optim_scheduler_conf = self.config['optim_scheduler']
        optim_scheduler_cls = net.optim.lr_scheduler.__dict__[
            optim_scheduler_conf['type']]
        optim_scheduler = optim_scheduler_cls(optimizer,
                                              **optim_scheduler_conf['kwargs'])
        return [optimizer], [optim_scheduler]

    def prepare_data(self):
        self.train_instances, self.val_instances = instance.get_train_val_instances(**self.config['instance'])

    def train_dataloader(self):
        dataset = loader.InstanceDataset(self.train_instances)
        return torch.utils.data.DataLoader(dataset, batch_size=self.batch_size)

    def val_dataloader(self):
        dataset = loader.InstanceDataset(self.val_instances)
        return torch.utils.data.DataLoader(dataset, batch_size=self.batch_size)

    @staticmethod
    def run(config):
        now = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        run_dir = path.join("wandb", now)
        run_dir = path.abspath(run_dir)
        os.environ['WANDB_RUN_DIR'] = run_dir

        checkpoint_callback = callbacks.ModelCheckpoint(
            run_dir, monitor=config['early_stopping']['monitor'])

        early_stopping_callback = callbacks.EarlyStopping(
            **config['early_stopping'])

        experiment = Experiment(config)
        trainer = pl.Trainer(logger=pl.loggers.WandbLogger(),
                             checkpoint_callback=checkpoint_callback,
                             early_stop_callback=early_stopping_callback,
                             **config['trainer'])

        trainer.fit(experiment)
