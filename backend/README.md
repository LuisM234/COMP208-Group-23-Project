<h1 align="center">Flashcards API</h1>

<p align="center">
    <strong>The backend of the flashcards project.</strong>
</p>

## Development
### Prerequisites
- `uv` (https://docs.astral.sh/uv/getting-started/installation/)

Assuming you've already installed `uv`, run the following command to:
- install Python if you haven't already
- install all the packages needed for the backend
- create a virtual environment for easier management over packages.

```bash
uv sync
```

### Adding and removing a new package/library
Simply run this to add:
```bash
uv add <package name>
```

And run this to remove:
```bash
uv remove <package name>
```
After you're happy with whatever you just installed, **make sure you commit AND push both `pyproject.toml` & `uv.lock` for other contributors.**

And if you notice `pyproject.toml` & `uv.lock` being updated, run `uv sync` immediately to keep your packages up to date.

### Running the backend API
To test your changes it's ideal to use the development way.

#### Development
Run this in your terminal (in the backend folder):
```bash
uv run fastapi dev
```

#### Production
We don't need to do this now, but when the time comes you run the following (also in the backend folder):
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
The endpoints would look like this: "<backend link>/deck/cards"

If this makes 0 sense, refer to these docs about FastAPI: https://fastapi.tiangolo.com/tutorial/bigger-applications/#another-module-with-apirouter

And probably have a look around the different sections of the library (or ask AI to be honest)

### How to use the database
Database stuff coming soon, once we figure out how to implement it.

Ideally we (Treasure, Charles) were thinking to use a cloud database, such as [TIDB](https://www.pingcap.com/).

We can host the backend on our machines, and have the database in the cloud so we don't have to worry about hosting the entire system anywhere. This is subject to change if anyone has any other ideas.