"""Démarre Django et publie automatiquement l'API avec ngrok sous Windows."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
PORT = 8000
LOCAL_URL = f"http://127.0.0.1:{PORT}"
TOKEN_PLACEHOLDERS = {"", "METS_TON_TOKEN_ICI", "YOUR_NGROK_AUTHTOKEN"}


def relaunch_with_virtualenv() -> None:
    """Crée l'environnement au besoin et relance ce script avec son Python."""
    if not VENV_PYTHON.exists():
        print("[setup] Création de l'environnement virtuel .venv...")
        subprocess.run([sys.executable, "-m", "venv", str(BASE_DIR / ".venv")], check=True)
        subprocess.run(
            [str(VENV_PYTHON), "-m", "pip", "install", "-r", str(BASE_DIR / "requirements.txt")],
            check=True,
        )

    if Path(sys.executable).resolve() != VENV_PYTHON.resolve():
        result = subprocess.run([str(VENV_PYTHON), str(Path(__file__).resolve())])
        raise SystemExit(result.returncode)


def ensure_dependencies() -> None:
    """Installe les dépendances si ngrok n'est pas encore présent dans .venv."""
    try:
        import pyngrok  # noqa: F401
    except ImportError:
        print("[setup] Installation des dépendances manquantes...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(BASE_DIR / "requirements.txt")],
            check=True,
        )


def wait_for_django(process: subprocess.Popen, timeout: int = 30) -> None:
    """Attend que Django écoute réellement sur le port local."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Django s'est arrêté avant d'être prêt (code {process.returncode})."
            )
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(f"Django n'a pas démarré sur le port {PORT} après {timeout} secondes.")


def port_is_open() -> bool:
    """Indique si un serveur répond déjà sur le port local de Django."""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
            return True
    except OSError:
        return False


def stop_existing_project_server() -> None:
    """Ferme seulement un ancien runserver appartenant à ce projet Windows."""
    if not port_is_open():
        return
    if os.name != "nt":
        raise RuntimeError(
            f"Le port {PORT} est déjà utilisé. Arrêtez l'ancien serveur avant de continuer."
        )
    project = str(BASE_DIR).replace("'", "''")
    script = f"""
$connections = Get-NetTCPConnection -LocalPort {PORT} -State Listen -ErrorAction SilentlyContinue
foreach ($connection in $connections) {{
  $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)" -ErrorAction SilentlyContinue
  if ($process.CommandLine -like '*{project}*' -and $process.CommandLine -like '*manage.py*runserver*') {{
    Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
  }}
}}
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        cwd=BASE_DIR,
        timeout=15,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5
    while port_is_open() and time.monotonic() < deadline:
        time.sleep(0.25)
    if port_is_open():
        raise RuntimeError(
            f"Le port {PORT} est utilisé par une autre application. Fermez-la puis relancez."
        )


def stop_process(process: subprocess.Popen | None) -> None:
    """Arrête proprement le serveur Django, puis force si nécessaire."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    relaunch_with_virtualenv()
    ensure_dependencies()

    from dotenv import load_dotenv
    from pyngrok import ngrok

    load_dotenv(BASE_DIR / ".env")
    token = os.getenv("NGROK_AUTHTOKEN", "").strip()
    if token in TOKEN_PLACEHOLDERS:
        print(
            "[erreur] Remplacez NGROK_AUTHTOKEN=METS_TON_TOKEN_ICI dans .env "
            "par votre vrai token ngrok."
        )
        return 1
    configured_api_url = os.getenv("COMMERCE_API_URL", "").strip()
    configured_domain = urlparse(configured_api_url).hostname if configured_api_url else None
    if configured_domain and "ngrok" not in configured_domain:
        configured_domain = None

    # Le domaine public doit être autorisé par Django sans ouvrir ALLOWED_HOSTS à '*'.
    current_hosts = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
    required_hosts = [".ngrok-free.dev", ".ngrok-free.app", ".ngrok.app"]
    os.environ["DJANGO_ALLOWED_HOSTS"] = ",".join(
        [current_hosts, *[host for host in required_hosts if host not in current_hosts]]
    )
    # Ne jamais exposer les pages de diagnostic détaillées de Django sur Internet.
    os.environ["DJANGO_DEBUG"] = "False"

    django_process = None
    public_url = None
    try:
        stop_existing_project_server()
        print(f"[django] Démarrage sur {LOCAL_URL}...")
        django_process = subprocess.Popen(
            [
                sys.executable,
                str(BASE_DIR / "manage.py"),
                "runserver",
                f"127.0.0.1:{PORT}",
                "--noreload",
            ],
            cwd=BASE_DIR,
        )
        wait_for_django(django_process)
        print("[django] Prêt.")

        print("[ngrok] Configuration et ouverture du tunnel...")
        ngrok.set_auth_token(token)
        # Toujours recréer le tunnel : une URL encore visible sur le port 4040
        # peut appartenir à un agent dont le heartbeat est déjà mort.
        try:
            ngrok.kill()
        except Exception:
            pass
        connect_options = {"addr": PORT, "proto": "http"}
        if configured_domain:
            connect_options["domain"] = configured_domain
        tunnel = ngrok.connect(**connect_options)
        public_url = tunnel.public_url.rstrip("/")

        if configured_domain and urlparse(public_url).hostname != configured_domain:
            raise RuntimeError(
                "Le tunnel ngrok n'utilise pas le domaine stable configuré dans COMMERCE_API_URL."
            )

        print("\n" + "=" * 68)
        print(f"API PUBLIQUE : {public_url}/api/commerce/")
        print(f"URL LOCALE   : {LOCAL_URL}/api/commerce/")
        print("n8n peut maintenant appeler l'URL publique ci-dessus.")
        print("Appuyez sur Ctrl+C pour arrêter Django et ngrok.")
        print("=" * 68 + "\n")

        while True:
            if django_process is not None and django_process.poll() is not None:
                raise RuntimeError(f"Django s'est arrêté (code {django_process.returncode}).")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[arrêt] Fermeture de Django et ngrok...")
        return 0
    except Exception as exc:
        print(f"\n[erreur] {exc}")
        return 1
    finally:
        if public_url:
            try:
                ngrok.disconnect(public_url)
            except Exception:
                pass
        try:
            ngrok.kill()
        except Exception:
            pass
        stop_process(django_process)


if __name__ == "__main__":
    raise SystemExit(main())
