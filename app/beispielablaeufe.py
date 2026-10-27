"""Vorschläge für häufige Handlungsabläufe der Radfahrausbildung.

Eine Schule übernimmt sie mit einem Klick in ihre eigenen Abläufe und passt sie
dort an – die Ausbildung unterscheidet sich je nach Region und Polizei. Die Texte
folgen dem Muster der Items: Kurzbezeichnung (Knopf am iPad), Beobachtungstext
(für die Eltern am Posten), Übungstext (für den Feedbackbogen, an das Kind gerichtet).
"""

from __future__ import annotations

# (Name, Beschreibung, [(Kurzbezeichnung, Beobachtungstext, Übungstext), …])
BEISPIELE: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "Linksabbiegen",
        "Direktes Linksabbiegen auf der Fahrbahn.",
        [
            ("Schulterblick links",
             "Schaut das Kind vor dem Einordnen über die linke Schulter nach hinten?",
             "Schau über die linke Schulter nach hinten, bevor du dich zur Mitte einordnest."),
            ("Handzeichen links",
             "Zeigt das Kind mit dem linken Arm deutlich an, wohin es fahren will?",
             "Strecke den linken Arm weit aus, damit alle sehen, wohin du willst."),
            ("Zur Mitte einordnen",
             "Fährt das Kind rechtzeitig zur Fahrbahnmitte bzw. auf die Linksabbiegerspur?",
             "Ordne dich rechtzeitig zur Straßenmitte hin ein."),
            ("Gegenverkehr beachten",
             "Lässt das Kind entgegenkommende Fahrzeuge vorbei, bevor es abbiegt?",
             "Lass entgegenkommende Fahrzeuge erst vorbeifahren."),
            ("Zweiter Schulterblick",
             "Schaut das Kind direkt vor dem Abbiegen noch einmal über die linke Schulter?",
             "Schau direkt vor dem Abbiegen noch einmal über die linke Schulter."),
            ("Zügig abbiegen",
             "Biegt das Kind zügig ab, ohne die Kurve zu schneiden?",
             "Biege zügig ab und schneide die Kurve nicht."),
        ],
    ),
    (
        "Rechtsabbiegen",
        "",
        [
            ("Schulterblick rechts",
             "Schaut das Kind vor dem Abbiegen über die rechte Schulter, z. B. nach anderen Radfahrern?",
             "Schau vor dem Abbiegen über die rechte Schulter."),
            ("Handzeichen rechts",
             "Zeigt das Kind mit dem rechten Arm deutlich an, dass es abbiegt?",
             "Strecke den rechten Arm aus, bevor du abbiegst."),
            ("Rechts halten",
             "Bleibt das Kind beim Abbiegen am rechten Fahrbahnrand?",
             "Bleib beim Rechtsabbiegen am rechten Rand."),
            ("Fußgänger beachten",
             "Lässt das Kind Fußgänger vorgehen, die die neue Straße überqueren?",
             "Lass Fußgänger in der neuen Straße zuerst gehen."),
            ("Langsam und bremsbereit",
             "Fährt das Kind langsam und mit den Fingern an den Bremsen um die Kurve?",
             "Fahre langsam und mit den Fingern an den Bremsen um die Kurve."),
        ],
    ),
    (
        "Anfahren vom Fahrbahnrand",
        "",
        [
            ("Schulterblick links",
             "Schaut das Kind vor dem Losfahren über die linke Schulter nach hinten?",
             "Schau über die linke Schulter, bevor du losfährst."),
            ("Handzeichen links",
             "Zeigt das Kind mit dem linken Arm an, dass es losfährt?",
             "Zeig mit dem linken Arm, dass du losfährst."),
            ("Verkehr vorbeilassen",
             "Wartet das Kind, bis die Fahrbahn frei ist?",
             "Fahr erst los, wenn die Straße frei ist."),
            ("Sicher anfahren",
             "Fährt das Kind zügig und ohne Schlenker an?",
             "Fahr zügig und geradeaus los."),
        ],
    ),
    (
        "Rechts vor links",
        "Kreuzung oder Einmündung ohne Verkehrszeichen.",
        [
            ("Langsam heranfahren",
             "Wird das Kind vor der Kreuzung langsamer?",
             "Fahr langsam auf die Kreuzung zu."),
            ("Nach rechts schauen",
             "Schaut das Kind nach rechts, ob jemand kommt?",
             "Schau nach rechts – wer von rechts kommt, darf zuerst fahren."),
            ("Vorfahrt gewähren",
             "Lässt das Kind Fahrzeuge von rechts vorbei?",
             "Lass Fahrzeuge von rechts vorbei."),
            ("Bremsbereit",
             "Hat das Kind die Finger an den Bremsen?",
             "Halte die Finger an den Bremsen, wenn es eng oder unübersichtlich wird."),
        ],
    ),
    (
        "Vorbeifahren an einem Hindernis",
        "Zum Beispiel an einem parkenden Auto.",
        [
            ("Schulterblick links",
             "Schaut das Kind vor dem Ausscheren über die linke Schulter?",
             "Schau über die linke Schulter, bevor du an einem Hindernis vorbeifährst."),
            ("Handzeichen links",
             "Zeigt das Kind das Ausscheren mit dem linken Arm an?",
             "Zeig mit dem linken Arm, dass du ausscherst."),
            ("Gegenverkehr beachten",
             "Wartet das Kind hinter dem Hindernis, wenn Gegenverkehr kommt?",
             "Warte hinter dem Hindernis, bis kein Gegenverkehr mehr kommt."),
            ("Abstand halten",
             "Hält das Kind etwa einen Meter Abstand zum Hindernis?",
             "Halte etwa einen Meter Abstand – eine Autotür kann plötzlich aufgehen."),
            ("Wieder rechts fahren",
             "Fährt das Kind nach dem Hindernis wieder an den rechten Rand?",
             "Fahr nach dem Hindernis wieder nach rechts."),
        ],
    ),
]
