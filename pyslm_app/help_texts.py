"""Explanations shown by the "?" help badges of the desktop application (Italian UI)."""

HELP = {
    # --- Componente -------------------------------------------------------------------------------------------------
    "void_screen": (
        "Impostazioni dello «Screen cavità voxel», che cerca volumi chiusi dentro il pezzo.\n"
        "• Passo voxel: dimensione dei cubetti di analisi; più piccolo trova cavità più sottili ma è più lento.\n"
        "• Diametro sonda: sfera usata per segnalare i passaggi verso l'esterno più stretti di questo diametro.\n"
        "È una stima geometrica: non verifica l'uscita reale della polvere."
    ),
    "density": (
        "Materiale e densità in g/cm³, usati solo per stimare il peso del pezzo dal suo volume.\n"
        "Scegliendo un materiale dal menu la densità si imposta da sola con un valore tipico del "
        "materiale stampato; puoi comunque modificarla con le frecce o scrivendola, e il menu passa a "
        "«Personalizzato». Le leghe reali possono variare di qualche percento."
    ),
    "orientation": (
        "Posizione del pezzo sul piatto di costruzione.\n"
        "• Asse X / Y / Z: rotazione del pezzo attorno a quell'asse, in gradi.\n"
        "• Sollevamento piatto: distanza tra il piatto e il punto più basso del pezzo (tipicamente "
        "3-5 mm), così anche le facce inferiori ricevono supporti; con 0 il pezzo appoggia sul piatto.\n"
        "Ogni modifica annulla i supporti generati, che vanno rigenerati."
    ),
    "section": (
        "Piano di sezione: taglia pezzo e supporti per vederne l'interno; la faccia di taglio appare "
        "piena (rosso mattone il pezzo, azzurro scuro i supporti). Cambia solo la visualizzazione.\n"
        "• Asse: Z taglia in orizzontale (per strati), X e Y in verticale.\n"
        "• Slider: sposta il piano; la sua quota è indicata accanto.\n"
        "• Inverti lato: nasconde l'altra metà."
    ),
    # --- Analisi overhang ------------------------------------------------------------------------------------------
    "overhang_angle": (
        "Le superfici rivolte verso il basso inclinate meno di questo angolo rispetto all'orizzontale "
        "vengono considerate a sbalzo e ricevono supporti. Aumentandolo si supportano anche superfici "
        "più ripide (più supporti); diminuendolo solo quelle quasi orizzontali. 45° è il valore tipico "
        "per i metalli."
    ),
    # --- Parametri comuni dei supporti ---------------------------------------------------------------------------
    "ray": (
        "Dimensione dei pixel delle mappe di altezza usate per trovare le regioni di supporto. Valori "
        "piccoli seguono più fedelmente i contorni del pezzo ma l'identificazione è più lenta."
    ),
    "outer_gap": (
        "Arretra il contorno esterno di ogni regione di supporto di questa distanza, lasciando un "
        "piccolo spazio dal bordo della superficie a sbalzo. Un'impronta larga meno del doppio di "
        "questo valore scompare; la soglia «Area minima» può eliminare altri frammenti."
    ),
    "inner_gap": (
        "Distanza lasciata tra regioni di supporto vicine che PySLM separa perché poggiano ad altezze "
        "molto diverse (ad esempio una parte sul piatto e una sul pezzo)."
    ),
    "simplify": (
        "Tolleranza con cui viene semplificato il contorno di ogni regione prima di costruire il "
        "volume di supporto. Valori più grandi danno contorni più semplici e calcoli più rapidi, ma "
        "meno aderenti alla forma del pezzo."
    ),
    "area": (
        "Le regioni di supporto con un'impronta più piccola di quest'area vengono scartate. Serve a "
        "eliminare frammenti minuscoli che non hanno bisogno di supporto."
    ),
    # --- Blocco a pareti ------------------------------------------------------------------------------------------
    "wall_spacing": (
        "Distanza tra due pareti vicine della griglia, in X e in Y. Valori piccoli danno supporti più "
        "fitti e robusti (più materiale e più facce); valori grandi supporti più leggeri e facili da "
        "rimuovere, ma la superficie del pezzo resta libera per tratti più lunghi."
    ),
    "wall_thickness": (
        "Spessore reale di ogni parete. Le pareti vengono esportate come solidi chiusi con questo "
        "spessore."
    ),
    "teeth_height": (
        "Altezza dei denti in cima (e in fondo) alle pareti. Denti più alti si staccano più facilmente "
        "dal pezzo ma lasciano una fascia piena più alta sotto di loro."
    ),
    "teeth_contact": (
        "Lunghezza della punta di ogni dente, cioè della zona che tocca il pezzo. Più è corta, più il "
        "supporto si stacca facilmente e meno segni lascia, ma tiene meno."
    ),
    "teeth_base": (
        "Larghezza di ogni dente dove si unisce alla parete. Deve essere almeno pari al contatto: la "
        "differenza dà la pendenza dei fianchi del dente."
    ),
    "teeth_penetration": (
        "Di quanto le punte dei denti entrano nel pezzo, per garantire che si saldino alla superficie. "
        "0 = i denti toccano appena la superficie."
    ),
    "perforation_size": (
        "Diagonale dei fori a rombo nelle pareti. Fori più grandi alleggeriscono le pareti e fanno "
        "uscire meglio la polvere, ma non entrano nelle pareti basse o strette, che restano piene."
    ),
    "perforation_web": (
        "Materiale lasciato tra due fori vicini e tra i fori e le estremità delle pareti. Valori "
        "piccoli danno pareti più traforate e leggere, ma più fragili."
    ),
    "solid_margin": (
        "Fascia piena, senza fori, lasciata sotto i denti superiori e sopra la base (o sopra i denti "
        "inferiori). Riducilo per forare anche le regioni basse; 0 porta i fori fino ai denti e "
        "alla base."
    ),
    "fragmentation": (
        "Interrompe le pareti a questo intervallo con un piccolo taglio verticale, così i supporti si "
        "staccano a pezzi più facilmente. 0 disattiva la frammentazione."
    ),
    "perforation": "Attiva o disattiva i fori a rombo nelle pareti.",
    "use_skin": (
        "Aggiunge una parete continua lungo il contorno di ogni regione di supporto (con il reticolo "
        "BCC: una parete di pilastri lungo il bordo)."
    ),
    "upper_teeth": (
        "Denti in cima alle pareti, dove toccano il pezzo: rendono i supporti più facili da staccare. "
        "Senza denti la parete tocca il pezzo per tutta la lunghezza."
    ),
    "lower_teeth": (
        "Denti in fondo alle pareti dove queste appoggiano sul pezzo. Sul piatto di costruzione la "
        "base resta sempre piena."
    ),
    # --- Reticolo BCC ---------------------------------------------------------------------------------------------
    "width": "Diametro delle aste del reticolo BCC.",
    "cell_size": (
        "Lato della cella del reticolo BCC: distanza tra i pilastri e tra i livelli del reticolo. "
        "Celle piccole danno un reticolo più fitto e più pesante."
    ),
    "border": "Distanza tra i pilastri della parete perimetrale del reticolo BCC.",
}
