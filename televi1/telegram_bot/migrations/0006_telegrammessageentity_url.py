# Generated by Django 4.2.13 on 2024-07-28 16:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('telegram_bot', '0005_telegramchat_uploadercondition_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegrammessageentity',
            name='url',
            field=models.URLField(null=True),
        ),
    ]
