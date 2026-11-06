from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("matches", "0002_reporting_views")]

    operations = [
        migrations.AddField(
            model_name="match",
            name="external_id",
            field=models.BigIntegerField(blank=True, null=True, unique=True, verbose_name="ID в PandaScore"),
        ),
        migrations.AddField(
            model_name="match",
            name="score_team1",
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Счёт серии, команда 1 (импорт)"),
        ),
        migrations.AddField(
            model_name="match",
            name="score_team2",
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Счёт серии, команда 2 (импорт)"),
        ),
    ]
