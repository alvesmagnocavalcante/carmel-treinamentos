from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('treinamentos', '0016_setores_da_humand'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='position',
            field=models.CharField(
                blank=True, max_length=150, verbose_name='Função',
                help_text='Cargo da pessoa (vem da Humand ou é escolhido por ela no cadastro).'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='self_declared',
            field=models.BooleanField(
                default=False, verbose_name='Dados escolhidos pela própria pessoa',
                help_text='No cadastro, a Humand não trazia setor, resort ou função e a pessoa escolheu. Vale conferir.'),
        ),
    ]
