from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.PublicLoginView.as_view(), name="login"),
    path("staff/login/", views.StaffLoginView.as_view(), name="staff_login"),
    path("register/customer/", views.CustomerRegisterView.as_view(), name="register_customer"),
    path("register/vendor/", views.VendorRegisterView.as_view(), name="register_vendor"),
    path("verify-otp/", views.VerifyOTPView.as_view(), name="verify_otp"),
    path("forgot-password/", views.ForgotPasswordView.as_view(), name="forgot_password"),
    path("reset-password/verify/", views.ResetPasswordOTPView.as_view(), name="reset_password_verify"),
    path("reset-password/set/", views.SetNewPasswordView.as_view(), name="set_new_password"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("api/check-email/", views.api_check_email, name="check_email"),
    path("api/check-username/", views.api_check_username, name="check_username"),
]
