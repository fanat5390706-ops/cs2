from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0004_player_photo_url_team_logo_url")]

    operations = [
        migrations.AddField(
            model_name="player",
            name="pandascore_id",
            field=models.BigIntegerField(blank=True, null=True, unique=True, verbose_name="ID в PandaScore"),
        ),
    ]
