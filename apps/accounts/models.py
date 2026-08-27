from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class FalconUserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "manager")
        extra_fields.setdefault("email_verified", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class FalconUser(AbstractBaseUser, PermissionsMixin):
    ROLE_CUSTOMER = "customer"
    ROLE_VENDOR = "vendor"
    ROLE_AGENT = "delivery_agent"
    ROLE_SUB_MANAGER = "sub_manager"
    ROLE_MANAGER = "manager"

    ROLE_CHOICES = [
        (ROLE_CUSTOMER, "Customer"),
        (ROLE_VENDOR, "Vendor"),
        (ROLE_AGENT, "Delivery Agent"),
        (ROLE_SUB_MANAGER, "Sub-Manager"),
        (ROLE_MANAGER, "Manager"),
    ]

    STAFF_ROLES = [ROLE_MANAGER, ROLE_SUB_MANAGER, ROLE_AGENT]
    PUBLIC_ROLES = [ROLE_CUSTOMER, ROLE_VENDOR]

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_CUSTOMER)
    is_active = models.BooleanField(default=True)
    email_verified = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = FalconUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"

    @property
    def is_manager_level(self):
        return self.role in (self.ROLE_MANAGER, self.ROLE_SUB_MANAGER)


class CustomerProfile(models.Model):
    user = models.OneToOneField(
        FalconUser, on_delete=models.CASCADE, related_name="customerprofile"
    )
    full_name = models.CharField(max_length=120)
    phone_number = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name


class VendorProfile(models.Model):
    user = models.OneToOneField(
        FalconUser, on_delete=models.CASCADE, related_name="vendorprofile"
    )
    business_name = models.CharField(max_length=160)
    username = models.CharField(max_length=40, unique=True)
    contact_name = models.CharField(max_length=120, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    is_verified = models.BooleanField(default=False)
    bank_name = models.CharField(max_length=120, blank=True)
    bank_code = models.CharField(max_length=12, blank=True)
    bank_account_number = models.CharField(max_length=10, blank=True)
    account_name = models.CharField(max_length=160, blank=True)
    bank_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.business_name


class DeliveryAgentProfile(models.Model):
    user = models.OneToOneField(
        FalconUser, on_delete=models.CASCADE, related_name="deliveryagentprofile"
    )
    full_name = models.CharField(max_length=120)
    phone_number = models.CharField(max_length=20, blank=True)
    assigned_zone = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)
    warehouse = models.ForeignKey(
        "core.Warehouse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agents",
    )
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name


class SubManagerProfile(models.Model):
    user = models.OneToOneField(
        FalconUser, on_delete=models.CASCADE, related_name="submanagerprofile"
    )
    full_name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name


class ManagerProfile(models.Model):
    user = models.OneToOneField(
        FalconUser, on_delete=models.CASCADE, related_name="managerprofile"
    )
    full_name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name


class OTPRecord(models.Model):
    PURPOSE_REGISTRATION = "registration"
    PURPOSE_PASSWORD_RESET = "password_reset"
    PURPOSE_CHOICES = [
        (PURPOSE_REGISTRATION, "Registration"),
        (PURPOSE_PASSWORD_RESET, "Password Reset"),
    ]

    user = models.ForeignKey(
        FalconUser, on_delete=models.CASCADE, related_name="otp_records"
    )
    otp_code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} - {self.purpose}"

    def is_valid(self):
        return not self.is_used and timezone.now() <= self.expires_at
