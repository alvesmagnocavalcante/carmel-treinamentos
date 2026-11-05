"""Ferramentas compartilhadas pelos testes (usuários, setores e pasta temporária)."""

import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from ..models import Department, TrainingVideo, UserProfile


TMP = Path(tempfile.mkdtemp(prefix="carmel-tests-"))


def make_user(username, role, dept=None, superuser=False):
    user = (User.objects.create_superuser if superuser else User.objects.create_user)(username, password="x123456")
    user.profile.role = role
    user.profile.department = dept
    user.profile.save()
    return user


@override_settings(TEMP_DOCS_DIR=TMP / "temp_docs")
class BaseTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.rh = Department.objects.create(code="rh", name="RH")
        self.gov = Department.objects.create(code="governanca", name="Governança")
        self.admin = make_user("admin", UserProfile.ROLE_ADMIN, superuser=True)
        self.gestor = make_user("gestor", UserProfile.ROLE_GESTOR, self.rh)
        self.colab = make_user("colab", UserProfile.ROLE_COLABORADOR, self.gov)
        self.sem_setor = make_user("semsetor", UserProfile.ROLE_COLABORADOR)
        self.v_rh = TrainingVideo.objects.create(department=self.rh, title="Vídeo RH", file_name="a.txt",
                                                 status="COMPLETED", video_url="https://x/a.mp4")
        self.v_gov = TrainingVideo.objects.create(department=self.gov, title="Vídeo Gov", file_name="b.txt",
                                                  status="COMPLETED", video_url="https://x/b.mp4")
