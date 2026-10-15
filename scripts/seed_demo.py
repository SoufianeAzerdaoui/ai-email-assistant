#!/usr/bin/env python3
"""Create a deterministic set of 30 French demo emails for an existing user."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_engine
from app.models import Email, Thread, User


DEMO_PREFIX = "demo-seed-v1"
THREADS = (
    {
        "subject": "Renouvellement du contrat de maintenance",
        "category": "client",
        "priority": 3,
        "senders": ["claire@atelier-lumiere.fr", "juridique@atelier-lumiere.fr"],
        "bodies": [
            "Bonjour, notre contrat arrive à échéance. Pouvez-vous nous envoyer une proposition actualisée ?",
            "Merci pour votre retour. Nous souhaitons conserver le même périmètre avec une assistance prioritaire.",
            "Notre service juridique a ajouté deux remarques sur les délais d’intervention.",
            "La direction valide le budget proposé. Pouvez-vous préparer la version à signer ?",
            "Le contrat signé est joint à ce message. Merci de confirmer sa bonne réception.",
        ],
    },
    {
        "subject": "Facture hébergement – septembre",
        "category": "facture",
        "priority": 2,
        "senders": ["facturation@cloudhexagone.fr", "compta@cloudhexagone.fr"],
        "bodies": [
            "Bonjour, vous trouverez votre facture mensuelle d’hébergement en pièce jointe.",
            "Nous constatons que le règlement n’apparaît pas encore sur votre compte client.",
            "Pouvez-vous nous transmettre la référence du virement afin de faire le rapprochement ?",
            "Le paiement a bien été identifié. Votre compte est maintenant à jour.",
            "Merci de conserver ce message comme confirmation de règlement.",
        ],
    },
    {
        "subject": "Organisation de la démonstration produit",
        "category": "rendez-vous",
        "priority": 3,
        "senders": ["sophie.martin@novacorp.fr", "thomas@novacorp.fr"],
        "bodies": [
            "Bonjour, seriez-vous disponible mardi prochain pour une démonstration à notre équipe ?",
            "Le créneau de 10 h convient à six participants. La réunion peut se tenir en visioconférence.",
            "Pourriez-vous prévoir un exemple autour du suivi des demandes clients ?",
            "Voici le lien de connexion et la liste définitive des participants.",
            "Merci pour la démonstration. Nous aimerions planifier un atelier technique complémentaire.",
        ],
    },
    {
        "subject": "La lettre numérique de la semaine",
        "category": "newsletter",
        "priority": 1,
        "senders": ["newsletter@frenchtech.example", "evenements@frenchtech.example"],
        "bodies": [
            "Cette semaine : financement, cybersécurité et nouveaux outils pour les équipes produit.",
            "Découvrez notre entretien avec trois entrepreneuses qui développent leur activité en Europe.",
            "Les inscriptions pour la rencontre mensuelle sont ouvertes jusqu’à vendredi.",
            "Notre sélection présente cinq ressources pratiques pour mieux mesurer la satisfaction client.",
            "Retrouvez les événements et appels à projets du mois prochain dans notre agenda.",
        ],
    },
    {
        "subject": "Offre exceptionnelle réservée aux professionnels",
        "category": "spam probable",
        "priority": 1,
        "senders": ["promo@offres-express.example", "contact@gains-rapides.example"],
        "bodies": [
            "Profitez aujourd’hui seulement d’une remise exceptionnelle sur notre catalogue professionnel.",
            "Votre entreprise a été sélectionnée pour recevoir un avantage exclusif sans engagement.",
            "Cliquez sur notre lien pour confirmer vos coordonnées avant la fin de la journée.",
            "Il ne reste que quelques heures pour bénéficier de cette proposition commerciale.",
            "Dernier rappel : votre avantage expirera ce soir à minuit.",
        ],
    },
    {
        "subject": "Mise à jour des accès au bureau",
        "category": "autre",
        "priority": 2,
        "senders": ["accueil@espace-republique.fr", "support@espace-republique.fr"],
        "bodies": [
            "Bonjour, le système de badges sera mis à jour ce week-end dans l’ensemble du bâtiment.",
            "Merci de vérifier votre numéro de badge dans votre espace locataire avant jeudi.",
            "Une permanence sera disponible vendredi matin pour remplacer les badges non reconnus.",
            "Les tests sont terminés et tous les accès principaux fonctionnent normalement.",
            "N’hésitez pas à contacter l’accueil si vous rencontrez encore une difficulté d’accès.",
        ],
    },
)
STATUSES = ("pending", "draft_ready", "replied", "ignored", "pending")


def seed_demo(db: Session, user: User) -> int:
    """Insert missing demo records and return the number of newly created emails."""
    gmail_ids = {
        value for value in db.scalars(
            select(Email.gmail_message_id).where(
                Email.user_id == user.id,
                Email.gmail_message_id.like(f"{DEMO_PREFIX}-message-%"),
            )
        )
    }
    base_date = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(days=30)
    created = 0

    for thread_number, definition in enumerate(THREADS, start=1):
        gmail_thread_id = f"{DEMO_PREFIX}-thread-{thread_number:02d}"
        thread = db.scalar(select(Thread).where(
            Thread.user_id == user.id,
            Thread.gmail_thread_id == gmail_thread_id,
        ))
        if thread is None:
            thread = Thread(
                user_id=user.id,
                gmail_thread_id=gmail_thread_id,
                subject=definition["subject"],
            )
            db.add(thread)
            db.flush()

        for message_number, body in enumerate(definition["bodies"], start=1):
            gmail_message_id = (
                f"{DEMO_PREFIX}-message-{thread_number:02d}-{message_number:02d}"
            )
            if gmail_message_id in gmail_ids:
                continue

            index = (thread_number - 1) * 5 + message_number - 1
            db.add(Email(
                user_id=user.id,
                thread_id=thread.id,
                gmail_message_id=gmail_message_id,
                message_id=f"<{gmail_message_id}@demo.local>",
                sender=definition["senders"][(message_number - 1) % len(definition["senders"])],
                recipients=[user.email],
                subject=(
                    definition["subject"]
                    if message_number == 1
                    else f"Re: {definition['subject']}"
                ),
                body_text=body,
                received_at=base_date + timedelta(days=index, hours=9 + message_number),
                category=definition["category"],
                priority=((definition["priority"] + message_number - 2) % 3) + 1,
                summary=body.split(".", maxsplit=1)[0] + ".",
                expected_action=(
                    "Répondre ou traiter la demande" if definition["priority"] > 1 else "Aucune action urgente"
                ),
                needs_review=definition["category"] in {"spam probable", "autre"},
                status=STATUSES[(thread_number + message_number) % len(STATUSES)],
            ))
            gmail_ids.add(gmail_message_id)
            created += 1

    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-email", required=True, help="Existing user's email address")
    args = parser.parse_args()
    normalized_email = args.user_email.strip().lower()

    with Session(get_engine()) as db:
        user = db.scalar(select(User).where(func.lower(User.email) == normalized_email))
        if user is None:
            parser.error(f"no existing user found for {normalized_email}")
        created = seed_demo(db, user)
        db.commit()
        total = db.scalar(select(func.count()).select_from(Email).where(
            Email.user_id == user.id,
            Email.gmail_message_id.like(f"{DEMO_PREFIX}-message-%"),
        ))

    print(f"Demo ready for {normalized_email}: {created} created, {total} total")


if __name__ == "__main__":
    main()
