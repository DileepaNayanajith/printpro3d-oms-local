# Learn while building PRINTPRO3D

## How a button becomes a saved order

The caller fills an HTML form in `oms/templates/index.html`. Flask receives it at `/leads` in `oms/__init__.py`, validates it and saves a lead, order and job in one SQLite transaction. The packing screen reads those same records, so screenshots are unnecessary.

`oms/automation.py` reserves one CCP number and queues preparation. `worker.py` sees that queue and asks `oms/fde_browser.py` to fill the portal. Each field is mapped explicitly: `#rName` gets the saved customer name, `#amount` gets COD in LKR, and the city is selected from FDE's own suggestions.

## First VS Code exercise

1. Open `oms/templates/help.html` and change one instruction to match how your staff speak.
2. Stop/restart the app, then open `/help` to see the change. The current server does not auto-reload.
3. In the terminal, run `.venv/bin/python -m unittest discover -s tests -v`.
4. Review changes with `git diff`, then save a commit: `git add oms/templates/help.html` and `git commit -m "Clarify packing instructions"`.
5. `git push` backs up the code to the private GitHub repository. It does not deploy or update a running app automatically.

VS Code already has interpreter, test discovery and debugger settings in `.vscode/`. Use **OMS web app** or **FDE worker (fill only)** in Run and Debug after stopping the existing process on that port. Install the recommended Microsoft Python extension if VS Code requests it.

## File map

| File | What to learn |
|---|---|
| `oms/templates/` | Visible screens and forms |
| `oms/__init__.py` | Routes, validation, permissions and data flow |
| `oms/automation.py` | Transactions, queue states and duplicate prevention |
| `oms/fde_browser.py` | Browser locators and exact field checks |
| `manage.py` | Staff accounts and password hashing |
| `serve.py` | Running one staff server on local Wi-Fi |
| `tests/` | Repeatable checks before changing real workflows |

Never add customer databases, passwords, browser profiles or official waybill PDFs to Git. They live in the ignored `instance/` folder. GitHub stores the application code; private local backups protect the order data separately.
