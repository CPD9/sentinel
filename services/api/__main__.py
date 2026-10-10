"""`python -m services.api` starts the API with uvicorn on 127.0.0.1 only (never a public port;
remote access goes through an SSH tunnel). Port 8001 is what the web app expects (web/.env.example);
8000 is kept free for the vLLM tunnel. Override with API_PORT."""
import os

import uvicorn


def main() -> None:
    uvicorn.run("services.api.main:app", host="127.0.0.1", port=int(os.environ.get("API_PORT", "8001")))


if __name__ == "__main__":
    main()
