from pydantic import BaseModel, ConfigDict, model_validator

DEFAULT_MAINTENANCE_MESSAGE = "Le site est actuellement en maintenance. Merci de revenir plus tard."


class SiteSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    maintenance_mode: bool = False
    maintenance_message: str = DEFAULT_MAINTENANCE_MESSAGE
    show_reviews_count: bool = True
    show_purchases_count: bool = True


class SiteSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    maintenance_mode: bool | None = None
    maintenance_message: str | None = None
    show_reviews_count: bool | None = None
    show_purchases_count: bool | None = None

    @model_validator(mode="after")
    def check_update(self) -> "SiteSettingsUpdate":
        if not self.model_fields_set:
            raise ValueError("Aucune modification fournie.")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError("Les valeurs nulles ne sont pas autorisées.")
        return self
