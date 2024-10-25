import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)

@app.command()
def run():
    # if is_swarm && host_network:
        # run_nf_agent()
    # elif is_swarm:
        # run_agent()
    # else:
        # run_full()
    pass

@app.command()
def run_agent():
    pass

@app.command()
def run_nf_agent():
    pass

@app.command("full-cleanup")
def full_cleanup():
    pass

if __name__ == "__main__":
    app()
