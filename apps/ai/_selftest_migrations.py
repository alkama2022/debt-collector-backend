"""
Static model <-> migration consistency check for every app touched by the
multilingual work. No Django required.

Verifies that every concrete field on a model has a corresponding CreateModel
or AddField in that app's migrations, and that migration dependencies point at
migrations that actually exist.

    .venv/Scripts/python.exe backend/apps/ai/_selftest_migrations.py
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, "..", ".."))
APPS = os.path.join(BACKEND, "apps")

# Managers and inherited/abstract helpers are never database columns.
NON_COLUMN = {"objects"}


def model_fields(path, classname):
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == classname:
            out = []
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    tgt = stmt.targets[0]
                    if isinstance(tgt, ast.Name):
                        out.append(tgt.id)
            return out
    raise SystemExit("class %s not found in %s" % (classname, path))


def migration_ops(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    added = {}
    deps = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            fname = node.func.attr
            if fname in ("AddField", "AlterField", "CreateModel"):
                kw = {k.arg: k.value for k in node.keywords}
                if fname == "CreateModel":
                    model = getattr(kw.get("name"), "value", None)
                    for elt in getattr(kw.get("fields"), "elts", []) or []:
                        t = getattr(elt, "value", elt)
                        if isinstance(t, ast.Tuple) and t.elts:
                            added.setdefault(str(model).lower(), set()).add(t.elts[0].value)
                else:
                    model = getattr(kw.get("model_name"), "value", None)
                    field = getattr(kw.get("name"), "value", None)
                    added.setdefault(str(model).lower(), set()).add(field)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Name) and t.id == "dependencies"
                        and isinstance(node.value, ast.List)):
                    for elt in node.value.elts:
                        try:
                            deps.append(ast.literal_eval(elt))
                        except Exception:
                            pass
    return added, deps


def app_migrations(app):
    mig_dir = os.path.join(APPS, app, "migrations")
    if not os.path.isdir(mig_dir):
        return []
    return sorted(
        f for f in os.listdir(mig_dir) if f.endswith(".py") and f[0].isdigit()
    )


def main():
    targets = {
        "ai": ["AIConversation", "AIMessage", "AIAgentAction", "PromiseToPay"],
        "audit": ["AICommunicationAudit", "AuditLog"],
        "comms": ["CommunicationEvent", "CommunicationPreference", "ReminderRule"],
        "voice": ["VoiceCall", "CallAttempt"],
    }

    ok = True
    all_deps = []

    for app, models in targets.items():
        migs = app_migrations(app)
        covered = {}
        for m in migs:
            added, deps = migration_ops(os.path.join(APPS, app, "migrations", m))
            for k, v in added.items():
                covered.setdefault(k, set()).update(v)
            all_deps.extend(deps)
        print("%s: %s\n" % (app, ", ".join(migs)))
        for cls in models:
            fields = set(model_fields(os.path.join(APPS, app, "models.py"), cls)) - NON_COLUMN
            have = covered.get(cls.lower(), set())
            missing = sorted(f for f in fields if f not in have)
            status = "OK" if not missing else "MISSING"
            if missing:
                ok = False
            print("   %-26s %-8s %2d/%d fields covered"
                  % (cls, status, len(fields) - len(missing), len(fields)))
            for f in missing:
                print("        - %s" % f)

    print("\ndependency resolution:")
    bad = []
    for a, m in all_deps:
        # swappable_dependency(settings.AUTH_USER_MODEL) is a function call,
        # not a (app, migration) tuple, so it never reaches all_deps.
        if a == "settings":
            # There is no "settings" app; AUTH_USER_MODEL deps must be
            # declared via migrations.swappable_dependency.
            bad.append((a, m, "must use migrations.swappable_dependency"))
            continue
        if not os.path.exists(os.path.join(APPS, a, "migrations", m + ".py")):
            bad.append((a, m, "migration file not found"))
    if bad:
        print("   PROBLEMS:")
        for entry in bad:
            print("      %s.%s -> %s" % entry)
        ok = False
    else:
        print("   all %d dependencies resolve" % len(all_deps))

    print("\n%s" % ("ALL CONSISTENT" if ok else "INCONSISTENCIES FOUND"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
