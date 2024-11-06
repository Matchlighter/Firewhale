import typer
from typing_extensions import Annotated

app = typer.Typer(no_args_is_help=True, add_completion=False)

@app.command()
def run(
    nfagent: Annotated[bool, typer.Option(show_default="If Swarm")] = None,
    redis: Annotated[bool, typer.Option(show_default="If Swarm")] = None,
):
    """ Start Firewhale """
    from .serve import serve
    serve(nfagent=nfagent, redis_url=redis)
    pass

@app.command()
def nfagent():
    """ Run Firewhale's NFAgent - a small service to handle proxying NFTables commands from inside to outside Swarm """
    pass

@app.command("full-cleanup")
def full_cleanup():
    """
    Remove all local Firewhale rules and chains.
    Must be run without the NFAgent - eg with `network_mode: host` and `cap_add: NET_ADMIN`.
    """
    from .base import full_cleanup
    from .nfbackends.local import LocalNFTBackend
    from .nfbackends import nf_backend_store
    nf_backend_store.set_backend(LocalNFTBackend())

    full_cleanup()

if __name__ == "__main__":
    app()
