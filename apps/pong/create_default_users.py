import os
from dotenv import load_dotenv
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site

load_dotenv()

social_app_name = '42'
social_app_exists = SocialApp.objects.filter(name=social_app_name).exists()
# The login page's "Login with 42" button needs this app to exist. Without a
# registered 42 OAuth app the button just fails at intra; local accounts still work.
client_id = os.getenv('OAUTH_CLIENT_ID') or 'not-configured'
client_secret = os.getenv('OAUTH_CLIENT_SECRET') or ''

if not social_app_exists:
    site = Site.objects.all()[0]
    social_app = SocialApp.objects.create(
        provider='provider',
        name='42',
        secret=client_secret,
        client_id=client_id,
    )
    social_app.sites.set([site])



username = 'AI_Ursula'
user_exists = User.objects.filter(username=username).exists()

if not user_exists:
    User.objects.create_user(username=username, password=make_password(''))

username = 'Local'
user_exists = User.objects.filter(username=username).exists()

if not user_exists:
    User.objects.create_user(username=username, password=make_password(''))

username = 'admin'
user_exists = User.objects.filter(username=username).exists()

if not user_exists:
    User.objects.create_superuser(username=username, password=os.getenv('USERS_ADMIN_PW'))