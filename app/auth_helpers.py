# app/auth_helpers.py

def get_admin_id(user):
    """Restituisce l'ID dell'admin effettivo (anche per admin_team)"""
    if user.role == "admin_team":
        return user.parent_id
    if user.role == "admin":
        return user.id
    if user.role == "superadmin":
        return None  # opzionale: potrebbe non servire
    return user.parent_id  # fallback se usato da dealer o dealer_team

def get_dealer_id(user):
    """Restituisce l'ID del dealer effettivo (anche per dealer_team)"""
    if user.role == "dealer_team":
        return user.parent_id
    if user.role == "dealer":
        return user.id
    return None

def is_admin_user(user):
    """True se l'utente è admin, admin_team o superadmin"""
    return user.role in ["admin", "admin_team", "superadmin"]

def is_dealer_user(user):
    """True se l'utente è dealer o dealer_team"""
    return user.role in ["dealer", "dealer_team"]

def is_team_user(user):
    """True se l'utente è parte di un team"""
    return user.role in ["admin_team", "dealer_team"]
