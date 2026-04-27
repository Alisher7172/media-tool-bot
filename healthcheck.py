from app.config import settings


def main() -> None:
    settings.validate()
    print("Healthcheck OK")


if __name__ == "__main__":
    main()