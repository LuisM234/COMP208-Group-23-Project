<h1 align="center">Flashcards API</h1>

<p align="center">
    <strong>The backend of the flashcards project.</strong>
</p>

## Development
### Setting up access to the repo
Because the repo is **private**, you may need to setup a **PAT** (Personal Access Token) or an **SSH key** for your GitHub account.
The *recommended* way is to use **SSH keys**, so you don't have to deal with applying tokens.
You may follow this tutorial by GitHub here:
https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent
https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account

Once you've done the SSH key setup, try to do `ssh -T git@github.com` in your terminal and see if something like this gets returned:
```sh
ubuntu@jar-wls:~$ ssh -T git@github.com
Hi jvrring! You've successfully authenticated, but GitHub does not provide shell access.
```

### Cloning the repo
If you followed the SSH key setup, you can use this in your terminal to clone the repo:
```bash
git clone git@github.com:LuisM234/COMP208-Group-23-Project.git
# Go into the group project folder
cd COMP208-Group-23-Project
```

> [!IMPORTANT]
> Make sure you're in the **backend** folder, otherwise the rest of this will not work!
> ```bash
> jarad@JacBook-Air COMP208-Group-23-Project % cd backend
> jarad@JacBook-Air backend % _
> ```

### Prerequisites
- `uv` (https://docs.astral.sh/uv/getting-started/installation/)

Assuming you've already installed `uv`, run the following command in your terminal to:
- install Python if you haven't already
- install all the packages needed for the backend
- create a virtual environment for easier management over packages.

```bash
uv sync
```

### Adding and removing a new package/library
Simply run this in your terminal to add:
```bash
uv add <package name>
```

And run this in your terminal to remove:
```bash
uv remove <package name>
```
#### After changing dependencies 
Make sure you commit both:
- `pyproject.toml` 
- `uv.lock`

and **push** them.

#### After pulling changes via `git pull`
If you notice `pyproject.toml` & `uv.lock` being updated, run this in your terminal:
```bash
uv sync
``` 
to keep your environment up to date.

### Running the backend API
To test your changes it's ideal to use the development way.

#### Development
Run this in your terminal (in the backend folder):
```bash
uv run fastapi dev
```

#### Production
We don't need to do this for now, but when the time comes you run the following (also in the backend folder):
```bash
uv run fastapi run
```

### Understanding backend structure
All routes like `/deck` or `/ai` go under the `routes/` folder.
Create a new `.py` file with a reasonable name and use this as a base (just an example):
```py
from fastapi import APIRouter

deck_route = APIRouter(prefix="/deck", tags=["Deck"])
```

and then create new **path operation decorators** with that specified router.
```py
@deck_route.get("/cards")
async def get_deck_cards():
    ...

@deck_route.post("/delete")
async def delete_deck():
    ...
```
The endpoints would look like this: `"<backend link>/deck/cards"`

> [!IMPORTANT]
> Make sure to add new routes into the `main.py` file like so:
>
> ```py
> # import your route here
> from routes.ai import ai_route
>
> # include the router
> app.include_router(ai_route)

If this makes 0 sense, refer to these docs about FastAPI: https://fastapi.tiangolo.com/tutorial/bigger-applications/#another-module-with-apirouter

And probably have a look around the different sections of the library (or ask AI to be honest)

### How to use the database
Database stuff coming soon, once we figure out how to implement it.

Ideally we (Treasure, Charles) were thinking to use a cloud database, such as [TIDB](https://www.pingcap.com/).

We can host the backend on our machines, and have the database in the cloud so we don't have to worry about hosting the entire system anywhere. This is subject to change if anyone has any other ideas.