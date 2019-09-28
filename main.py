%%writefile /content/LayoutGAN/main.py
"""A verification to the idea of LayoutGAN
Referred to https://github.com/sngjuk/LayoutGAN

Entrance of the program.
Copyright ©2019-current, Junru Zhong, All rights reserved.
"""

from __future__ import print_function

import random

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.utils.data
import torchvision.datasets
from tensorboardX import SummaryWriter
from torch.utils.checkpoint import checkpoint

import models


class MnistLayoutDataset(torch.utils.data.Dataset):
    """MNIST dataset and create torch dataset object."""

    def __init__(self, path, element_num=128, gt_thresh=200):
        super(MnistLayoutDataset, self).__init__()
        self.train_data = torch.load(path + "/MNIST/processed/training.pt")[0]
        self.element_num = element_num
        # Guess: a threshold (阈值) to indicate this pixel is lighted (0-255).
        self.gt_thresh = gt_thresh

    def __getitem__(self, index):
        """Extract layout features from images."""
        img = self.train_data[index]  # Load an image.
        gt_values = []

        for id, i in enumerate(img):
            for jd, j in enumerate(i):
                # If the current grayscale value is larger than the threshold, note this point.
                if j >= self.gt_thresh:
                    # Create the layout element.
                    # Meaning of `np.float32(2 * id +1) /56`?
                    gt_values.append(torch.Tensor([1, np.float32(2 * id + 1) / 56, np.float32(2 * jd + 1) / 56]))

        graph_elements = []

        # Shuffle, insert the images in a random order.
        for _ in range(self.element_num):
            ridx = random.randint(0, len(gt_values) - 1)
            graph_elements.append(gt_values[ridx])

        # MNIST layout elements format [1, x, y]
        return torch.stack(graph_elements)

    def __len__(self):
        return len(self.train_data)


def real_loss(D_out, smooth=False):
    """Loss function from the discriminator to the generator (when result is real).
    """
    labels = None
    batch_size = D_out.size(0)
    if smooth:
        labels = torch.ones(batch_size, 128) * 0.9
    else:
        labels = torch.ones(batch_size, 128)
    crit = nn.BCEWithLogitsLoss()
    loss = crit(D_out.squeeze(), labels)
    return loss


def fake_loss(D_out):
    """Loss function from the discriminator to the generator (when result is fake).
    """
    batch_size = D_out.size(0)
    labels = torch.zeros(batch_size, 128)
    crit = nn.BCEWithLogitsLoss()
    loss = crit(D_out.squeeze(), labels)
    return loss


def train_mnist(device, writer):
    # Root directory for dataset.
    dataroot = "data"
    # Number of workers for dataloader
    dataloader_workers = 0
    # Batch size during training
    batch_size = 20
    # Number of classes
    cls_num = 1
    # Number of geometry parameter
    geo_num = 2
    # Number of training epochs
    num_epochs = 1  # Not provided in the article.
    # Leaning rate for optimizers
    learning_rate = 0.00002
    # Beta1/2 hyperparameter for Adam optimizers (check the theory).
    beta1 = 1.0  # Not provided in the article.
    beta2 = 1.0

    # Download MNIST dataset
    _ = torchvision.datasets.MNIST(
        root=dataroot, train=True, download=True, transform=None)

    # Load MNIST dataset with layout processed.
    train_mnist_layout = MnistLayoutDataset(dataroot)
    train_mnist_layout_loader = torch.utils.data.DataLoader(
        train_mnist_layout, batch_size=batch_size, num_workers=dataloader_workers)

    # Initialize the generator and discriminator.
    # element_num: 128 random points for each MNIST image.
    generator = models.Generator(
        n_gpu, class_num=cls_num, element_num=128, feature_size=3).to(device)
    # element_num: 128 random points for each MNIST image.
    discriminator = models.RelationDiscriminator(
        n_gpu, class_num=cls_num, element_num=128, feature_size=3).to(device)
    print(generator)  # Check information of the generator.
    print(discriminator)  # Check information of the discriminator.

    # Write models to TensorBoardX
    # writer.add_graph(generator)
    # writer.add_graph(discriminator)

    # Initialize optimizers for models.
    print('Initialize optimizers.')
    generator_optimizer = optim.Adam(generator.parameters(), learning_rate)
    discriminator_optimizer = optim.Adam(discriminator.parameters(), learning_rate)

    # Initialize training parameters.
    print('Initialize training.')
    generator.train()
    discriminator.train()

    # Start training.
    for epoch in range(num_epochs):
        print('Start to train epoch %d.' % epoch)
        for batch_i, real_images in enumerate(train_mnist_layout_loader):

            print('In batch {0} of epoch {1}.'.format(batch_i + 1, epoch + 1))

            real_images = real_images.to(device)
            batch_size = real_images.size(0)

            # Train discriminator
            discriminator_optimizer.zero_grad()
            print('Start train discriminator with real images.')
            discriminator_real = discriminator(real_images)
            discriminator_real_loss = real_loss(discriminator_real, False)
            # TensorboardX
            writer.add_scalar('Discriminator Real Loss', discriminator_real_loss, epoch + batch_i)
            print('Finish train discriminator with real images.')

            # Size of the zlist does not equal to element number.
            # Zlist size should be [batch_size, element_num, feature_size]
            # Refer to real image size: [batch_size, element_num, cls + geo_info]
            zlist = []
            for i in range(batch_size):
                cls_z = np.ones((128, cls_num))
                geo_z = np.random.normal(0, 1, size=(128, geo_num))

                z = torch.Tensor(np.concatenate((cls_z, geo_z), axis=1))
                zlist.append(z)

            print('Generating fake images.')
            fake_images = generator(torch.stack(zlist))
            print('Finish generating fake images.')
            print('Discriminating fake images.')
            discriminator_fake = discriminator(fake_images)
            print('Calculating discriminator loss.')
            discriminator_fake_loss = fake_loss(discriminator_fake)
            # TensorboardX
            writer.add_scalar('Discriminator Fake Loss', discriminator_fake_loss, epoch + batch_i)
            discriminator_loss = discriminator_real_loss + discriminator_fake_loss
            # TensorboardX
            writer.add_scalar('Discriminator Total Loss', discriminator_loss, epoch + batch_i)
            print('Discriminator back propagation.')
            discriminator_loss.backward()
            discriminator_optimizer.step()
            print('Finish discriminating fake images.')

            # Reset the generator.
            generator_optimizer.zero_grad()
            zlist2 = []
            for i in range(batch_size):
                cls_z = np.ones((128, cls_num))
                geo_z = np.random.normal(0, 1, size=(128, geo_num))

                z = torch.Tensor(np.concatenate((cls_z, geo_z), axis=1))
                zlist2.append(z)

            print('Generating fake images 2.')
            fake_images2 = generator(torch.stack(zlist2))

            print('Discriminating fake images 2.')
            discriminator_fake = discriminator(fake_images2)

            print('Calculating loss of the generator.')
            generator_loss = real_loss(discriminator_fake, False)

            print('Generator back propagation.')
            generator_loss.backward()
            generator_optimizer.step()

            # TensorboardX
            writer.add_scalar('Generator Loss', generator_loss, epoch + batch_i)

            # Generated image shape [batch_index, element_index, class + position]
            # Transfer PyTorch tensor to numpy ndarray.
            if device is not 'cpu':
                images = fake_images2.cpu().detach().numpy()
            else:
                images = fake_images2.detach().numpy()
            figures = []
            for img_index in range(batch_size):
                x = images[img_index][:][:, 1]
                y = images[img_index][:][:, 2]
                figure = plt.figure()
                plt.scatter(x, y)
                figures.append(figure)

            # TensorBoardX
            writer.add_figure('Generated Points', figures, epoch + batch_i)

            print('Epoch [{:5d}/{:5d}] | discriminator_loss: {:6.4f} | generator_loss: {:6.4f}'.
                  format(epoch + 1, num_epochs, discriminator_loss.item(), generator_loss.item()))


if __name__ == '__main__':
    # Enable this in CUDA environment.
    n_gpu = 1  # Testing CPU mode.
    if torch.cuda.is_available() and n_gpu > 0:
        device = torch.device("cuda:0")
        torch.set_default_tensor_type('torch.cuda.FloatTensor')
    else:
        device = "cpu"
    # TensorBoardX: create writer
    writer = SummaryWriter()
    train_mnist(device, writer)
    writer.close()
