#!/usr/bin/env -S uv run --script
# -*- python -*-
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "click",
#     "tomlkit",
# ]
# ///

import subprocess
import pathlib
import click
import tomlkit

def get_pkg_name(script_path):
    """Python modules must use underscores."""
    return pathlib.Path(script_path).stem.replace("-", "_")

def get_bin_name(script_path):
    """The CLI command name should match the filename exactly."""
    return pathlib.Path(script_path).stem

def setup_umbrella(path):
    """Initialize the umbrella package if it doesn't exist."""
    umbrella_dir = pathlib.Path(path)
    pyproject_path = umbrella_dir / "pyproject.toml"
    
    if not umbrella_dir.exists():
        click.echo(f"Initializing umbrella package at {path}...")
        subprocess.run(["uv", "init", "--lib", str(umbrella_dir)], check=True)
    
    return pyproject_path

def update_umbrella_deps_bin(pyproject_path, pkg_name, bin_name, git_url):
    """Idempotently add dependency AND entry point to the umbrella."""
    with open(pyproject_path, "r") as f:
        data = tomlkit.load(f)

    # 1. Add to dependencies
    deps = data.get("project", {}).get("dependencies", [])
    entry = f"{pkg_name} @ {git_url}"
    if entry not in deps:
        deps.append(entry)
        data["project"]["dependencies"] = deps

    # 2. Add to project.scripts (The Proxy Entry Point)
    if "scripts" not in data["project"]:
        data["project"]["scripts"] = {}
    
    # This maps 'bin-name' to 'pkg_name.main:main' inside the umbrella
    data["project"]["scripts"][bin_name] = f"{pkg_name}.main:main"

    with open(pyproject_path, "w") as f:
        f.write(tomlkit.dumps(data))

def update_umbrella_deps(pyproject_path, pkg_name, git_url):
    """Idempotently add the dependency to the umbrella pyproject.toml."""
    with open(pyproject_path, "r") as f:
        data = tomlkit.load(f)

    deps = data.get("project", {}).get("dependencies", [])
    
    # Check if already present (either as a name or a git link)
    entry = f"{pkg_name} @ {git_url}"
    if entry not in deps:
        click.echo(f"Adding {pkg_name} to umbrella dependencies...")
        deps.append(entry)
        data["project"]["dependencies"] = deps
        with open(pyproject_path, "w") as f:
            f.write(tomlkit.dumps(data))
    else:
        click.echo(f"{pkg_name} already registered in umbrella.")

@click.command()
@click.argument('scripts', nargs=-1, type=click.Path(exists=True))
@click.option('--register', type=click.Path(), help="Path to the 'my-tools' umbrella package.")
@click.option('--giturl-pattern', default="git+https://github.com/brettviren/{repo}", 
              help="Pattern for git dependency URLs.")
def migrate(scripts, register, giturl_pattern):
    """Migrate standalone Python scripts to uv-managed packages."""
    
    for script in scripts:
        script_path = pathlib.Path(script)
        bin_name = get_bin_name(script_path)
        pkg_name = get_pkg_name(script_path)
        pkg_dir = pathlib.Path.cwd() / bin_name
        
        click.echo(f"\nProcessing: {bin_name}")

        # 1. Create Package Directory (Idempotent)
        if not pkg_dir.exists():
            subprocess.run([
                "uv", "init", "--lib", "--build-backend", "setuptools", str(pkg_dir)
            ], check=True)
        
        # 2. Setup src structure and main.py
        src_dir = pkg_dir / "src" / pkg_name
        src_dir.mkdir(parents=True, exist_ok=True)
        main_py = src_dir / "main.py"
        
        if not main_py.exists():
            content = script_path.read_text()
            if "def main()" not in content:
                # Basic wrap if no main exists
                indented = "\n".join(f"    {line}" for line in content.splitlines())
                content = f"def main():\n{indented}\n\nif __name__ == '__main__':\n    main()"
            main_py.write_text(content)

        # 3. Handle README.org
        (pkg_dir / "README.md").unlink(missing_ok=True)
        readme_org = pkg_dir / "README.org"
        if not readme_org.exists():
            readme_org.write_text(f"* {bin_name}\n\nMigrated from `{script_path.name}`")

        # 4. Update local pyproject.toml (Idempotent)
        pp_path = pkg_dir / "pyproject.toml"
        with open(pp_path, "r") as f:
            pp_data = tomlkit.load(f)

        # Set Org Readme
        pp_data["project"]["readme"] = {
            "file": "README.org", 
            "content-type": "text/org"
        }
        
        # Set Entry Point (The CLI command name)
        if "scripts" not in pp_data["project"]:
            pp_data["project"]["scripts"] = {}
        pp_data["project"]["scripts"][bin_name] = f"{pkg_name}.main:main"

        with open(pp_path, "w") as f:
            f.write(tomlkit.dumps(pp_data))

        # 5. Git Init (Idempotent)
        if not (pkg_dir / ".git").exists():
            subprocess.run(["git", "init"], cwd=pkg_dir, check=True)
            
        if not (pkg_dir / ".gitignore").exists():
            with open(pkg_dir / ".gitignore") as f:
                f.write('*~\n')
            subprocess.run(["git", "add", "."], cwd=pkg_dir, check=True)
            subprocess.run(["git", "commit", "-m", "Initial migration"], cwd=pkg_dir, check=True)

        # 6. Optional Umbrella Registration
        if register:
            umbrella_pp = setup_umbrella(register)
            git_url = giturl_pattern.format(repo=bin_name)
            update_umbrella_deps_bin(umbrella_pp, pkg_name, bin_name, git_url)

if __name__ == "__main__":
    migrate()
