"""Vorschläge für häufige Handlungsabläufe der Radfahrausbildung.

Eine Schule übernimmt sie mit einem Klick in ihre eigenen Abläufe und passt sie
dort an – die Ausbildung unterscheidet sich je nach Region und Polizei. Die Texte
folgen dem Muster der Items: Kurzbezeichnung (Knopf am iPad), Beobachtungstext
(für die Eltern am Posten), Übungstext (für den Feedbackbogen, an das Kind gerichtet).

Der Beobachtungstext ist bewusst eine Frage: Am Posten steht er unter „Darauf
achtest du an diesem Posten" auf dem Posten-Blatt, und die begleitende Person soll
ihn mit ja oder nein beantworten können (geprüft in tests/test_ablaeufe.py).
Der Übungstext spricht das Kind an und nennt möglichst konkret, was es üben soll.

Die Texte stammen aus einer ausgearbeiteten Übungsstrecke und sind hier von
Straßennamen gelöst, damit sie an jeder Schule passen.
"""

from __future__ import annotations

# (Name, Beschreibung, [(Kurzbezeichnung, Beobachtungstext, Übungstext), …])
BEISPIELE: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "Aus einer Ausfahrt auf die Straße",
        "Zum Beispiel aus dem Schulhof. Wer über einen abgesenkten Bordstein kommt, "
        "muss alle anderen vorlassen – auch die von links.",
        [
            ("Links und rechts schauen",
             "Schaut das Kind deutlich nach links und nach rechts und dreht dabei den Kopf?",
             "Bevor du auf die Straße fährst, schau nach links und nach rechts. Dreh dabei "
             "richtig den Kopf. Erst wenn frei ist, fährst du weiter."),
            ("Auf fließenden Verkehr achten",
             "Wartet das Kind an der Ausfahrt, bis kein Auto und kein Fahrrad mehr kommt?",
             "Die Autos und Fahrräder auf der Straße haben Vorrang, wenn du aus einer "
             "Ausfahrt kommst. Warte an der Ausfahrt, bis die Straße frei ist. Erst dann "
             "fährst du los."),
            ("Auf Fußgänger achten",
             "Lässt das Kind Fußgänger auf dem Gehweg vorbei, bevor es über den Gehweg fährt?",
             "Bevor du auf die Straße kommst, fährst du über den Gehweg. Schau, ob dort "
             "jemand geht, und lass ihn zuerst vorbei."),
            ("Mit beiden Händen anfahren",
             "Hat das Kind beim Anfahren beide Hände am Lenker und fährt es ohne Schlenker los?",
             "Wenn du losfährst, hast du immer beide Hände am Lenker. So kannst du gut lenken "
             "und bremsen. Übe das Anfahren: Pedal nach oben stellen, kräftig treten, "
             "geradeaus fahren."),
        ],
    ),
    (
        "Linksabbiegen",
        "Direktes Linksabbiegen auf der Fahrbahn. Der schwierigste Ablauf – zweimal umschauen.",
        [
            ("Schulterblick links",
             "Dreht das Kind vor dem Einordnen Kopf und Oberkörper deutlich über die linke "
             "Schulter nach hinten – nicht nur die Augen?",
             "Bevor du nach links fährst, schau dich über deine linke Schulter nach hinten um. "
             "Dreh dabei richtig den Kopf, nicht nur die Augen. So siehst du Autos, die von "
             "hinten kommen. Übe das auf dem Schulhof: geradeaus fahren, umschauen – und dabei "
             "trotzdem gerade bleiben."),
            ("Handzeichen links",
             "Streckt das Kind den linken Arm deutlich und lange genug waagerecht zur Seite aus "
             "und nimmt die Hand danach wieder sicher an den Lenker?",
             "Streck deinen linken Arm gerade zur Seite aus, damit alle sehen: Du willst nach "
             "links. Halte ihn ein paar Sekunden ausgestreckt. Übe das langsam auf dem Schulhof, "
             "bis du dabei sicher geradeaus fahren kannst."),
            ("Zur Fahrbahnmitte einordnen",
             "Fährt das Kind bis kurz rechts neben die Fahrbahnmitte, statt am rechten Rand zu "
             "bleiben?",
             "Wenn du links abbiegen willst, fahr nach dem Umschauen und dem Handzeichen bis "
             "kurz vor die Mitte der Straße. Bleib dabei rechts von der Mitte. So können Autos "
             "hinter dir rechts an dir vorbeifahren."),
            ("Links und rechts schauen",
             "Schaut das Kind vor dem Abbiegen deutlich nach links und nach rechts?",
             "Bevor du abbiegst, schau nach links und nach rechts. Dreh dabei richtig den Kopf. "
             "Erst wenn frei ist, fährst du weiter."),
            ("Gegenverkehr beachten",
             "Lässt das Kind entgegenkommende Fahrzeuge und Radfahrer zuerst fahren?",
             "Wer dir entgegenkommt, darf zuerst fahren, wenn du links abbiegst. Warte in der "
             "Mitte, bis niemand mehr entgegenkommt. Erst dann biegst du ab."),
            ("Nochmals nach links hinten umsehen",
             "Schaut das Kind unmittelbar vor dem Abbiegen ein zweites Mal über die linke "
             "Schulter nach hinten?",
             "Kurz bevor du abbiegst, schau dich noch einmal über die linke Schulter um. In der "
             "Zwischenzeit kann ein Auto oder Fahrrad von hinten gekommen sein. Merke: Zweimal "
             "umschauen beim Linksabbiegen!"),
            ("Im großen Bogen abbiegen",
             "Biegt das Kind in einem weiten Bogen ab, ohne die Kurve zu schneiden?",
             "Beim Linksabbiegen fährst du einen großen Bogen. Schneide die Kurve nicht ab, "
             "sonst kommst du auf die falsche Straßenseite. Stell dir vor, du fährst um die "
             "Mitte der Kreuzung herum."),
            ("Auf Fußgänger achten",
             "Lässt das Kind Fußgänger gehen, die die neue Straße überqueren?",
             "Beim Abbiegen gehen oft Menschen über die Straße, in die du hineinfährst. Sie "
             "dürfen zuerst gehen. Schau deshalb beim Abbiegen auch auf den Gehweg und warte, "
             "wenn jemand kommt."),
        ],
    ),
    (
        "Rechtsabbiegen",
        "",
        [
            ("Handzeichen rechts",
             "Streckt das Kind den rechten Arm deutlich waagerecht zur Seite aus, bevor es "
             "abbiegt?",
             "Streck deinen rechten Arm gerade zur Seite aus, damit alle sehen: Du willst nach "
             "rechts. Übe das auf dem Schulhof, bis du dabei mit einer Hand sicher fahren kannst."),
            ("Schulterblick rechts",
             "Schaut das Kind über die rechte Schulter nach hinten, etwa nach Radfahrern, die "
             "rechts vorbeifahren wollen?",
             "Bevor du rechts abbiegst, schau über deine rechte Schulter nach hinten. Dort "
             "könnte ein anderes Fahrrad kommen, das geradeaus fahren will."),
            ("Rücksicht auf Fußgänger",
             "Bremst das Kind ab und lässt Fußgänger gehen, die die neue Straße überqueren?",
             "Wenn du rechts abbiegst, gehen oft Menschen über die Straße. Sie dürfen zuerst. "
             "Bremse und lass sie gehen."),
            ("Im engen Bogen abbiegen",
             "Biegt das Kind in einem engen Bogen ab und bleibt dabei am rechten Fahrbahnrand?",
             "Beim Rechtsabbiegen fährst du einen kleinen, engen Bogen und bleibst ganz rechts. "
             "Fahr nicht weit in die Straße hinein."),
        ],
    ),
    (
        "Rechts vor links",
        "Kreuzung oder Einmündung ohne Verkehrszeichen.",
        [
            ("Vorsichtig heranfahren",
             "Fährt das Kind langsam und mit den Fingern an den Bremsen an die Kreuzung heran?",
             "Fahr langsam an die Kreuzung heran. Halte die Finger an den Bremsen. Dann kannst "
             "du sofort anhalten, wenn jemand kommt."),
            ("Nach allen Seiten schauen",
             "Schaut das Kind an der Kreuzung deutlich nach links, nach rechts und nach vorne?",
             "An einer Kreuzung kann von allen Seiten jemand kommen. Schau nach links, nach "
             "rechts und nach vorne, bevor du weiterfährst."),
            ("Vorfahrt: rechts vor links",
             "Lässt das Kind Fahrzeuge von rechts zuerst fahren und wartet es, bis frei ist?",
             "An dieser Stelle gilt: Wer von rechts kommt, darf zuerst fahren. Schau also "
             "besonders nach rechts und warte, wenn dort jemand kommt."),
        ],
    ),
    (
        "Vorbeifahren an einem Hindernis",
        "Zum Beispiel an einem parkenden Auto – wie ein kleines Linksabbiegen.",
        [
            ("Schulterblick und Handzeichen",
             "Schaut das Kind vor dem Ausscheren über die linke Schulter und zeigt es mit dem "
             "linken Arm an?",
             "Wenn rechts Autos parken, musst du an ihnen vorbei. Das ist wie ein kleines "
             "Abbiegen: Erst über die linke Schulter umschauen, dann den linken Arm ausstrecken, "
             "dann vorbeifahren."),
            ("Bei Gegenverkehr warten",
             "Wartet das Kind hinter dem Hindernis, bis der Gegenverkehr vorbei ist?",
             "Wenn dir ein Auto entgegenkommt, darfst du nicht an den geparkten Autos "
             "vorbeifahren. Bleib hinter dem geparkten Auto stehen und warte, bis der "
             "Gegenverkehr vorbei ist."),
            ("Etwa 1 m Seitenabstand",
             "Fährt das Kind mit etwa einem Meter Abstand am Hindernis vorbei?",
             "Fahr mit ungefähr einem Meter Abstand an parkenden Autos vorbei – das ist etwa so "
             "viel wie dein Fahrrad lang ist. Dann trifft dich keine Autotür, die plötzlich "
             "aufgeht."),
            ("Wieder rechts fahren",
             "Fährt das Kind nach dem Hindernis wieder an den rechten Rand?",
             "Fahr nach dem Hindernis wieder nach rechts."),
        ],
    ),
    (
        "Anhalten und Absteigen",
        "Ende der Prüfungsfahrt.",
        [
            ("Anhalten und absteigen",
             "Hält das Kind kontrolliert mit beiden Bremsen an und steigt es sicher ab?",
             "Am Ziel fährst du langsam, bremst mit beiden Bremsen, hältst an und steigst ab. "
             "Fahr nicht einfach weiter."),
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
]
