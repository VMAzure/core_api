import schedule
import time
from app.database import SessionLocal
from app.models import User

def charge_monthly_fee():
    db = SessionLocal()
    settings = db.execute("SELECT dealer_monthly_cost FROM settings").fetchone()
    dealer_monthly_cost = settings.dealer_monthly_cost

    admins = db.query(User).filter(User.role == "admin").all()

    for admin in admins:
        active_dealers = db.query(User).filter(User.role == "dealer", User.parent_id == admin.id).count()
        total_cost = active_dealers * dealer_monthly_cost

        if admin.credit >= total_cost:
            admin.credit -= total_cost
            print(f"✅ Credito scalato per {admin.email}: {total_cost} crediti")
        else:
            print(f"❌ Credito insufficiente per {admin.email}. Dealer sospesi!")

        db.commit()

    db.close()

# Eseguiamo il job ogni 30 giorni
schedule.every(30).days.do(charge_monthly_fee)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(86400)  # Controlla ogni giorno
