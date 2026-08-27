from django.db import models


class Warehouse(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=12, unique=True)
    address = models.TextField()
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} — {self.address}" if self.address else self.name
