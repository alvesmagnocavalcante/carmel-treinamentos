"""Resorts: quem vê qual vídeo, quem escolhe os resorts na revisão e o fim do menu "Grupos"."""

from django.urls import reverse

from ..models import Resort, TrainingVideo, UserProfile, VideoProgress
from .base import BaseTestCase, make_user


class ResortAccessTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.wind = Resort.objects.get(code="wind")
        self.taiba = Resort.objects.get(code="taiba")
        self.charme = Resort.objects.get(code="charme")
        # colaboradores do mesmo setor (Governança), em resorts diferentes
        self.c_wind = self.colab_in("c_wind", self.wind)
        self.c_taiba = self.colab_in("c_taiba", self.taiba)
        self.c_both = self.colab_in("c_both", self.wind, self.taiba)
        self.c_none = self.colab_in("c_none")
        self.only_wind = self.video("Só Wind", self.wind)
        self.wind_taiba = self.video("Wind e Taiba", self.wind, self.taiba)
        # self.v_gov (da base) não tem resort: vale para todos

    def colab_in(self, username, *resorts):
        user = make_user(username, UserProfile.ROLE_COLABORADOR, self.gov)
        user.profile.resorts.set(resorts)
        return user

    def video(self, title, *resorts):
        video = TrainingVideo.objects.create(department=self.gov, title=title, file_name="x.txt",
                                             status="COMPLETED", video_url="https://x/v.mp4")
        video.resorts.set(resorts)
        return video

    def titles_for(self, user):
        self.client.force_login(user)
        return {v.title for v in self.client.get(reverse("home")).context["videos"]}

    def test_seed_creates_the_resorts_with_the_humand_names(self):
        self.assertEqual(set(Resort.objects.values_list("name", flat=True)),
                         {"CM", "Magna", "Charme", "Wind", "Taíba", "Icaraizinho"})

    def test_video_without_resort_is_visible_to_everyone_in_the_department(self):
        for user in (self.c_wind, self.c_taiba, self.c_both, self.c_none):
            self.assertIn("Vídeo Gov", self.titles_for(user))

    def test_video_with_resorts_is_visible_only_to_those_resorts(self):
        self.assertEqual(self.titles_for(self.c_wind), {"Vídeo Gov", "Só Wind", "Wind e Taiba"})
        self.assertEqual(self.titles_for(self.c_taiba), {"Vídeo Gov", "Wind e Taiba"})
        self.assertEqual(self.titles_for(self.c_both), {"Vídeo Gov", "Só Wind", "Wind e Taiba"})

    def test_person_without_resort_sees_only_videos_for_all_resorts(self):
        self.assertEqual(self.titles_for(self.c_none), {"Vídeo Gov"})

    def test_video_is_not_duplicated_when_person_matches_two_resorts(self):
        self.client.force_login(self.c_both)
        videos = list(self.client.get(reverse("home")).context["videos"])
        self.assertEqual(len(videos), len({v.id for v in videos}))

    def test_department_still_limits_even_with_matching_resort(self):
        self.assertNotIn("Vídeo RH", self.titles_for(self.c_wind))
        other = TrainingVideo.objects.create(department=self.rh, title="RH Wind", file_name="r.txt", status="COMPLETED")
        other.resorts.set([self.wind])
        self.assertNotIn("RH Wind", self.titles_for(self.c_wind))

    def test_admin_sees_every_resort(self):
        self.assertTrue({"Só Wind", "Wind e Taiba", "Vídeo Gov"} <= self.titles_for(self.admin))

    def test_hidden_video_cannot_be_registered_or_streamed(self):
        self.client.force_login(self.c_taiba)
        self.assertEqual(self.client.post(reverse("register_view", args=[self.only_wind.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("stream_video", args=[self.only_wind.id])).status_code, 404)
        self.assertFalse(VideoProgress.objects.filter(user=self.c_taiba, video=self.only_wind).exists())
        self.client.force_login(self.c_wind)
        self.assertEqual(self.client.post(reverse("register_view", args=[self.only_wind.id])).status_code, 200)


class ResortReviewTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.wind = Resort.objects.get(code="wind")
        self.taiba = Resort.objects.get(code="taiba")
        self.gestor.profile.resorts.set([self.wind])
        self.job = TrainingVideo.objects.create(department=self.rh, title="POP", file_name="p.txt",
                                                status="AWAITING_REVIEW", script_text="Olá, equipe.")

    def approve(self, user, **data):
        self.client.force_login(user)
        return self.client.post(reverse("review_script", args=[self.job.id]), {"script": "Texto aprovado.", **data})

    def test_manager_only_offers_own_resorts(self):
        self.client.force_login(self.gestor)
        resp = self.client.get(reverse("review_script", args=[self.job.id]))
        self.assertEqual([r.code for r in resp.context["resort_choices"]], ["wind"])

    def test_admin_offers_every_active_resort(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("review_script", args=[self.job.id]))
        self.assertEqual(len(resp.context["resort_choices"]), Resort.objects.filter(active=True).count())
        self.assertEqual(len(resp.context["resort_choices"]), 6)  # CM, Magna, Charme, Wind, Taíba e Icaraizinho

    def test_manager_can_pick_own_resort(self):
        self.approve(self.gestor, resorts=[self.wind.id])
        self.assertEqual(set(self.job.resorts.all()), {self.wind})

    def test_manager_cannot_pick_a_resort_that_is_not_theirs(self):
        self.approve(self.gestor, resorts=[self.wind.id, self.taiba.id])
        self.assertEqual(set(self.job.resorts.all()), {self.wind})

    def test_admin_can_pick_any_resort(self):
        self.approve(self.admin, resorts=[self.wind.id, self.taiba.id])
        self.assertEqual(set(self.job.resorts.all()), {self.wind, self.taiba})

    def test_none_selected_means_all_resorts(self):
        self.approve(self.admin)
        self.assertEqual(self.job.resorts.count(), 0)

    def test_manager_keeps_resorts_outside_their_scope(self):
        self.job.resorts.set([self.taiba])  # definido por um administrador
        self.gestor.profile.resorts.set([self.wind, self.taiba])
        self.approve(self.gestor, resorts=[self.wind.id])
        # o gestor controla Wind e Taiba: ao desmarcar Taiba ela sai; nada fora do escopo dele é tocado
        self.assertEqual(set(self.job.resorts.all()), {self.wind})

    def test_manager_cannot_review_video_of_another_resort(self):
        self.job.resorts.set([self.taiba])
        self.client.force_login(self.gestor)
        self.assertEqual(self.client.get(reverse("review_script", args=[self.job.id])).status_code, 404)


class ResortAdminTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_groups_are_gone_and_resorts_are_in(self):
        self.assertEqual(self.client.get("/admin/auth/group/").status_code, 404)
        self.assertEqual(self.client.get(reverse("admin:treinamentos_resort_changelist")).status_code, 200)

    def test_user_and_video_forms_have_the_resort_field(self):
        resp = self.client.get(reverse("admin:auth_user_change", args=[self.colab.id]))
        self.assertContains(resp, "id_profile-0-resorts")
        resp = self.client.get(reverse("admin:treinamentos_trainingvideo_change", args=[self.v_rh.id]))
        self.assertContains(resp, "id_resorts")
        self.assertEqual(self.client.get(reverse("admin:auth_user_changelist")).status_code, 200)
