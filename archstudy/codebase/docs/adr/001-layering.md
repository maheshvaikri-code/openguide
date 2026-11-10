# ADR-001: Requests flow handler -> service -> repository -> database (rule V1)

**Status:** accepted

A request enters through a **handler**, which calls a **service**; a service uses **repositories** (and the cache and the shared
HTTP client); only a repository touches the **database**. Layers do not skip: a handler never imports a repository, the database
module, the cache or the HTTP client; a service never imports the database module or a handler; a repository never imports a
service or a handler. Imports only go down this stack.

**Why:** a business rule written in a handler cannot be reused or tested without the web layer, and a service that runs its own
queries cannot be tested without a database. Keeping one direction keeps each layer replaceable.

**What to do instead:** put the logic in the service layer and call it from the handler; put the query in a repository and call it
from the service.
