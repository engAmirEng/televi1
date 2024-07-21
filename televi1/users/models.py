import random
import string

from polymorphic.managers import PolymorphicManager
from polymorphic.models import PolymorphicModel

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from televi1.utils.models import TimeStampedModel


class UserManager(PolymorphicManager, BaseUserManager):
    async def make_username(self, base=None, length=15) -> str:
        if base:
            base = f"{base}-"
        else:
            base = ""
        length -= len(base)
        characters = string.ascii_letters + string.digits
        while True:
            username = base + "".join(random.choice(characters) for _ in range(length))
            if not await self.filter(username=username).aexists():
                return username


class User(TimeStampedModel, AbstractUser, PolymorphicModel):
    # The unique user for users among different bots
    # First and last name do not cover name patterns around the globe
    name = models.CharField(_("Name of User"), blank=True, max_length=255)
    first_name = None  # type: ignore
    last_name = None  # type: ignore

    objects = UserManager()
