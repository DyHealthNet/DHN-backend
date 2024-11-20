from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

class MySocialAccountAdapter(DefaultSocialAccountAdapter):
    def get_connect_redirect_url(self, request, socialaccount):
        """
        Skip the consent screen by directly redirecting to GitHub.
        """
        # Redirect directly to GitHub, skipping the intermediate consent screen.
        return socialaccount.get_login_url(request)
    def is_auto_signup_allowed(self, request, sociallogin):
        """
        Skip intermediate consent step and allow auto-login.
        """
        # Auto-signup is allowed if the social account can be used without a consent step
        return True