# ADR-005: Network access only inside app/http_client.py (rule H1)

**Status:** accepted

Network primitives (`socket`, `ssl`, `http.client`, `ftplib`, `smtplib`, `poplib`, `imaplib`, `telnetlib`, `xmlrpc.client`) are
used only in `app/http_client.py`. No other module opens a connection of any kind.

**Why:** ADR-003 only holds if there is no second, lower-level way to reach the network.
