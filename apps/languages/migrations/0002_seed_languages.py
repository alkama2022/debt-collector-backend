from django.db import migrations


def seed_languages(apps, schema_editor):
    Language = apps.get_model("languages", "Language")
    languages = [
        {"code": "en", "name": "English", "native_name": "English", "locale": "en-NG", "text_supported": True, "speech_to_text_supported": True, "text_to_speech_supported": True, "active": True},
        {"code": "ha", "name": "Hausa", "native_name": "Hausa", "locale": "ha-NG", "text_supported": True, "speech_to_text_supported": True, "text_to_speech_supported": True, "active": True},
        {"code": "yo", "name": "Yoruba", "native_name": "Yorùbá", "locale": "yo-NG", "text_supported": True, "speech_to_text_supported": True, "text_to_speech_supported": True, "active": True},
        {"code": "ig", "name": "Igbo", "native_name": "Igbo", "locale": "ig-NG", "text_supported": True, "speech_to_text_supported": True, "text_to_speech_supported": True, "active": True},
        {"code": "pcm", "name": "Nigerian Pidgin", "native_name": "Naija Pidgin", "locale": "pcm-NG", "text_supported": True, "speech_to_text_supported": True, "text_to_speech_supported": True, "active": True},
        {"code": "ar", "name": "Arabic", "native_name": "العربية", "locale": "ar-NG", "text_supported": True, "speech_to_text_supported": False, "text_to_speech_supported": False, "active": False},
        {"code": "fr", "name": "French", "native_name": "Français", "locale": "fr-NG", "text_supported": True, "speech_to_text_supported": False, "text_to_speech_supported": False, "active": False},
    ]
    for lang in languages:
        Language.objects.get_or_create(code=lang["code"], defaults=lang)


def reverse_seed(apps, schema_editor):
    Language = apps.get_model("languages", "Language")
    Language.objects.filter(code__in=["en", "ha", "yo", "ig", "pcm", "ar", "fr"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("languages", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_languages, reverse_seed),
    ]
