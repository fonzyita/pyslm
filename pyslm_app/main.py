"""PySLM desktop entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from .help_texts import HELP
from .materials import CUSTOM_MATERIAL, MATERIALS
from .themes import DEFAULT_THEME, THEMES, stylesheet
from .services import ModelSession, OrientationCandidate
from .viewer import MeshView


_ACRONYMS = {"BCC", "STL", "SLM", "X", "Y", "Z"}


def _sentence_case(text: str) -> str:
    """'PIANO DI COSTRUZIONE · Z = 0' -> 'Piano di costruzione · Z = 0' (single letters and 3D stay)."""
    title, sep, rest = text.partition("|")
    if sep:
        return _sentence_case(title) + sep + rest
    words = [w.lower() if w.isalpha() and w not in _ACRONYMS else w for w in text.split(" ")]
    result = " ".join(words)
    for i, ch in enumerate(result):
        if ch.isalpha():
            return result[:i] + ch.upper() + result[i + 1:]
    return result


class _HelpBadge(QtWidgets.QLabel):
    """A small "?" that shows its explanation as soon as the mouse is over it."""

    def __init__(self, text: str) -> None:
        super().__init__("?")
        self.setObjectName("helpBadge")
        self.setFixedSize(16, 16)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setCursor(QtCore.Qt.WhatsThisCursor)
        self.setToolTip(_tooltip_html(text))

    def enterEvent(self, event: Any) -> None:
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), self.toolTip(), self)
        super().enterEvent(event)


def _tooltip_html(text: str) -> str:
    # Rich text lets Qt wrap long explanations instead of showing one very long line
    return f"<p style='white-space: pre-wrap; max-width: 320px;'>{text}</p>"


class _SupportGeometryWorker(QtCore.QObject):
    """Identifies the support regions and builds their geometry off the GUI thread.

    Neither step uses OpenGL (height maps are projected on the CPU), so the
    window stays responsive for the whole generation.
    """

    identified = QtCore.pyqtSignal(int)
    # Overall percentage (0-100) and a description of the current step
    progress = QtCore.pyqtSignal(int, str)
    finished = QtCore.pyqtSignal(list, list)
    failed = QtCore.pyqtSignal(str)

    # Share of the overall progress taken by the region identification
    IDENTIFICATION_SHARE = 0.3

    def __init__(self, identify: Callable[[Callable[[float], None]], List[Any]]) -> None:
        super().__init__()
        self._identify = identify
        self._last_percent = -1

    def _report(self, fraction: float, message: str) -> None:
        percent = int(max(0.0, min(1.0, fraction)) * 100)
        # Only signal real changes so the GUI thread is not flooded with events
        if percent != self._last_percent:
            self._last_percent = percent
            self.progress.emit(percent, message)

    @QtCore.pyqtSlot()
    def run(self) -> None:
        share = self.IDENTIFICATION_SHARE
        try:
            regions = self._identify(
                lambda fraction: self._report(share * fraction, "Identificazione regioni di supporto")
            )
            self.identified.emit(len(regions))

            def build_progress(fraction: float, index: int, count: int) -> None:
                region = min(index + 1, count)
                self._report(
                    share + (1.0 - share) * fraction,
                    f"Costruzione geometria: regione {region} di {count}",
                )

            generated, meshes = ModelSession.build_support_geometry(regions, build_progress)
        except Exception as error:
            logging.exception("Generazione supporti PySLM non riuscita")
            self.failed.emit(str(error))
            return
        self.finished.emit(generated, meshes)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.session = ModelSession()
        self._updating_orientation = False
        self._internal_void_mesh: Optional[Any] = None
        self._probe_blocked_mesh: Optional[Any] = None
        self.orientation_candidates: List[OrientationCandidate] = []
        self._support_thread: Optional[QtCore.QThread] = None
        self._support_worker: Optional["_SupportGeometryWorker"] = None
        self.help_badges: dict = {}
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setFixedWidth(260)
        self.progress_bar.setVisible(False)
        self.setWindowTitle("PySLM | Metal AM Preparation")
        self.resize(1440, 900)
        self._build_ui()
        self._apply_style()
        self._log(
            "Pronto. Le coordinate STL sono interpretate in millimetri; "
            "la densità predefinita è solo una stima per acciaio."
        )

    def _build_ui(self) -> None:
        self._build_toolbar()
        self._build_panels()
        self._build_diagnostics()
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().showMessage("Nessun componente caricato")

    def _build_toolbar(self) -> None:
        toolbar = self.addToolBar("File")
        self._toolbar = toolbar
        toolbar.setMovable(False)
        toolbar.addAction("Importa STL", self._choose_stl)
        toolbar.addSeparator()
        toolbar.addAction("Esporta componente", self._export_part)
        toolbar.addAction("Esporta supporti", self._export_supports)
        toolbar.addAction("Esporta assieme", self._export_assembly)

    def _build_panels(self) -> None:
        outer = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(outer)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(12)

        self.left_panel = QtWidgets.QFrame()
        self.left_panel.setObjectName("sidePanel")
        left_layout = QtWidgets.QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(7)

        left_layout.addWidget(self._section_title("COMPONENTE"))
        self.import_button = QtWidgets.QPushButton("Apri file STL")
        self.import_button.clicked.connect(self._choose_stl)
        left_layout.addWidget(self.import_button)
        self.file_label = self._value_label("Nessun file caricato")
        self.file_label.setWordWrap(True)
        left_layout.addWidget(self.file_label)
        self.mesh_diagnostics_button = QtWidgets.QPushButton("Diagnostica geometria")
        self.mesh_diagnostics_button.clicked.connect(self._analyze_mesh)
        left_layout.addWidget(self.mesh_diagnostics_button)
        self.void_pitch_input = self._double_input(1.0, 0.1, 20.0, 2)
        self.probe_diameter_input = self._double_input(0.5, 0.1, 20.0, 2)
        void_pitch_row = QtWidgets.QHBoxLayout()
        void_pitch_row.addWidget(QtWidgets.QLabel("Passo voxel (mm)"))
        # One explanation for both settings of the cavity screen
        void_pitch_row.addWidget(
            self._help_badge("void_screen", self.void_pitch_input, self.probe_diameter_input)
        )
        void_pitch_row.addWidget(self.void_pitch_input)
        left_layout.addLayout(void_pitch_row)
        probe_diameter_row = QtWidgets.QHBoxLayout()
        probe_diameter_row.addWidget(QtWidgets.QLabel("Diametro sonda (mm)"))
        probe_diameter_row.addWidget(self.probe_diameter_input)
        left_layout.addLayout(probe_diameter_row)
        self.void_pitch_input.valueChanged.connect(
            self._void_screen_settings_changed
        )
        self.probe_diameter_input.valueChanged.connect(
            self._void_screen_settings_changed
        )
        self.screen_voids_button = QtWidgets.QPushButton("Screen cavità voxel")
        self.screen_voids_button.setToolTip(
            "Stima a risoluzione limitata dei volumi interni non connessi "
            "all'esterno e dei passaggi per una sonda sferica; "
            "non verifica l'evacuazione della polvere."
        )
        self.screen_voids_button.clicked.connect(self._screen_internal_voids)
        left_layout.addWidget(self.screen_voids_button)

        left_layout.addWidget(self._section_title("GEOMETRIA"))
        self.geometry_label = self._value_label("Dimensioni: —")
        self.volume_label = self._value_label("Volume: —")
        self.mass_label = self._value_label("Peso teorico: —")
        left_layout.addWidget(self.geometry_label)
        left_layout.addWidget(self.volume_label)
        # Material menu: picking a material sets its typical density, which stays editable
        self.material_input = QtWidgets.QComboBox()
        for name, density in MATERIALS:
            density_text = f"{density:.2f}".replace(".", ",")
            self.material_input.addItem(f"{name}  ·  {density_text} g/cm³", density)
        self.material_input.addItem(CUSTOM_MATERIAL, None)
        left_layout.addWidget(self.material_input)
        density_row = QtWidgets.QHBoxLayout()
        density_row.addWidget(QtWidgets.QLabel("Densità (g/cm³)"))
        self.density_input = self._double_input(MATERIALS[0][1], 0.001, 30.0, 3)
        self.density_input.valueChanged.connect(self._update_metrics)
        self.density_input.valueChanged.connect(self._density_edited)
        self.material_input.currentIndexChanged.connect(self._material_selected)
        density_row.addWidget(
            self._help_badge("density", self.material_input, self.density_input)
        )
        density_row.addWidget(self.density_input)
        left_layout.addLayout(density_row)
        left_layout.addWidget(self.mass_label)

        orientation_title_index = left_layout.count()
        self.rotation_inputs = []
        for axis in ("X", "Y", "Z"):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel(f"Asse {axis}"))
            spin = self._double_input(0.0, -360.0, 360.0, 1)
            spin.setSingleStep(5.0)
            spin.valueChanged.connect(self._apply_orientation)
            self.rotation_inputs.append(spin)
            row.addWidget(spin)
            left_layout.addLayout(row)
        lift_row = QtWidgets.QHBoxLayout()
        lift_row.addWidget(QtWidgets.QLabel("Sollevamento piatto (mm)"))
        self.lift_input = self._double_input(3.0, 0.0, 50.0, 2)
        self.lift_input.setSingleStep(0.5)
        self.lift_input.valueChanged.connect(self._apply_build_lift)
        lift_row.addWidget(self.lift_input)
        left_layout.addLayout(lift_row)
        # One explanation for the whole group, beside its title
        left_layout.insertWidget(
            orientation_title_index,
            self._title_with_help(
                "ORIENTAMENTO · GRADI", "orientation", *self.rotation_inputs, self.lift_input
            ),
        )
        self.compare_orientations_button = QtWidgets.QPushButton(
            "Confronta 24 orientamenti"
        )
        self.compare_orientations_button.clicked.connect(self._compare_orientations)
        left_layout.addWidget(self.compare_orientations_button)
        self.orientation_results = QtWidgets.QListWidget()
        self.orientation_results.setMinimumHeight(125)
        self.orientation_results.setMaximumHeight(190)
        self.orientation_results.setToolTip(
            "Classifica preliminare PySLM per momento-area supporti stimato."
        )
        left_layout.addWidget(self.orientation_results)
        self.apply_orientation_button = QtWidgets.QPushButton(
            "Applica orientamento selezionato"
        )
        self.apply_orientation_button.setEnabled(False)
        self.apply_orientation_button.clicked.connect(self._apply_selected_orientation)
        left_layout.addWidget(self.apply_orientation_button)
        left_layout.addStretch(1)

        viewer_panel = QtWidgets.QFrame()
        viewer_layout = QtWidgets.QVBoxLayout(viewer_panel)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_layout.setSpacing(6)
        viewer_heading = QtWidgets.QLabel(
            "PIANO DI COSTRUZIONE · Z = 0"
            "     |     Trascina: orbita   ·   Tasto destro: trasla   ·   Rotella: zoom"
        )
        viewer_heading.setObjectName("sectionTitle")
        viewer_layout.addWidget(viewer_heading)
        brightness_row = QtWidgets.QHBoxLayout()
        brightness_row.addWidget(QtWidgets.QLabel("Luminosità modello"))
        self.brightness_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.brightness_slider.setRange(0, 100)
        self.brightness_slider.setValue(50)
        self.brightness_value_label = QtWidgets.QLabel("50%")
        self.brightness_value_label.setMinimumWidth(36)
        brightness_row.addWidget(self.brightness_slider, 1)
        brightness_row.addWidget(self.brightness_value_label)
        viewer_layout.addLayout(brightness_row)

        # Section plane moved through the part and supports
        self.section_check = QtWidgets.QCheckBox("Sezione")
        self.section_axis = QtWidgets.QComboBox()
        for axis in ("Z", "X", "Y"):
            self.section_axis.addItem(f"Asse {axis}", axis.lower())
        self.section_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.section_slider.setRange(0, 1000)
        self.section_slider.setValue(500)
        self.section_flip = QtWidgets.QCheckBox("Inverti lato")
        self.section_label = QtWidgets.QLabel("—")
        self.section_label.setMinimumWidth(110)
        section_row = QtWidgets.QHBoxLayout()
        section_row.setSpacing(8)
        section_row.addWidget(self.section_check)
        # One explanation for the whole section group (axis, slider and side)
        section_row.addWidget(
            self._help_badge(
                "section", self.section_check, self.section_axis, self.section_slider, self.section_flip
            )
        )
        section_row.addWidget(self.section_axis)
        section_row.addWidget(self.section_slider, 1)
        section_row.addWidget(self.section_label)
        section_row.addWidget(self.section_flip)
        viewer_layout.addLayout(section_row)
        self.section_check.toggled.connect(self._update_section)
        self.section_axis.currentIndexChanged.connect(self._update_section)
        self.section_slider.valueChanged.connect(self._update_section)
        self.section_flip.toggled.connect(self._update_section)
        self.viewer = MeshView()
        self.brightness_slider.valueChanged.connect(self._set_viewer_brightness)
        viewer_layout.addWidget(self.viewer, 1)
        self._update_section()

        self.right_panel = QtWidgets.QFrame()
        self.right_panel.setObjectName("sidePanel")
        right_layout = QtWidgets.QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(7)
        right_layout.addWidget(self._section_title("ANALISI OVERHANG"))
        self.angle_input = self._double_input(45.0, 1.0, 89.0, 1)
        right_layout.addLayout(
            self._labelled_with_help("Angolo limite (°)", "overhang_angle", self.angle_input)
        )
        self.angle_input.valueChanged.connect(self._support_settings_changed)
        right_layout.addWidget(self.angle_input)
        self.overhang_label = self._value_label("Superfici critiche: —")
        self.overhang_label.setWordWrap(True)
        right_layout.addWidget(self.overhang_label)
        self.analyze_button = QtWidgets.QPushButton("Analizza superfici")
        self.analyze_button.clicked.connect(self._analyze_overhangs)
        right_layout.addWidget(self.analyze_button)

        right_layout.addWidget(self._section_title("TIPO DI SUPPORTO"))
        self.support_type = QtWidgets.QComboBox()
        self.support_type.addItem("Blocco a pareti (stile SLM)", "walls")
        self.support_type.addItem("Reticolo spaziale BCC", "grid_truss")
        self.support_type.addItem("Volume a blocco", "block")
        self.support_type.currentIndexChanged.connect(self._support_type_changed)
        right_layout.addWidget(self.support_type)
        # Collapsible parameter group: the header arrow opens and closes it to save space
        self.support_heading = QtWidgets.QToolButton()
        self.support_heading.setObjectName("collapseHeader")
        self.support_heading.setText("PARAMETRI BLOCCO A PARETI")
        self.support_heading.setCheckable(True)
        self.support_heading.setChecked(False)
        self.support_heading.setArrowType(QtCore.Qt.RightArrow)
        self.support_heading.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.support_heading.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.support_heading.setToolTip("Clicca per mostrare o nascondere i parametri dei supporti.")
        right_layout.addWidget(self.support_heading)
        self.support_params_panel = QtWidgets.QWidget()
        params_layout = QtWidgets.QVBoxLayout(self.support_params_panel)
        params_layout.setContentsMargins(0, 0, 0, 0)
        params_layout.setSpacing(7)
        right_layout.addWidget(self.support_params_panel)
        self.support_params_panel.setVisible(False)
        self.support_heading.toggled.connect(self._toggle_support_parameters)
        self.support_inputs = {
            "ray": self._add_parameter(params_layout, "Risoluzione proiezione (mm)", 0.2, 0.01, 2.0, 2, help_key="ray"),
            "outer_gap": self._add_parameter(params_layout, "Offset esterno (mm)", 0.5, 0.0, 10.0, 2, help_key="outer_gap"),
            "inner_gap": self._add_parameter(params_layout, "Offset interno (mm)", 0.2, 0.0, 10.0, 2, help_key="inner_gap"),
            "simplify": self._add_parameter(params_layout, "Semplificazione contorno (mm)", 0.5, 0.0, 10.0, 2, help_key="simplify"),
            "area": self._add_parameter(params_layout, "Area minima (mm²)", 1.0, 0.0, 1000.0, 2, help_key="area"),
        }
        # Parameters of the SLM-style wall supports
        self.wall_panel = QtWidgets.QWidget()
        wall_layout = QtWidgets.QVBoxLayout(self.wall_panel)
        wall_layout.setContentsMargins(0, 0, 0, 0)
        wall_layout.setSpacing(7)
        self.support_inputs.update({
            "wall_spacing": self._add_parameter(wall_layout, "Passo pareti (mm)", 2.5, 0.5, 20.0, 2, help_key="wall_spacing"),
            "wall_thickness": self._add_parameter(wall_layout, "Spessore parete (mm)", 0.3, 0.05, 5.0, 2, help_key="wall_thickness"),
            "teeth_height": self._add_parameter(wall_layout, "Altezza denti (mm)", 0.8, 0.1, 5.0, 2, help_key="teeth_height"),
            "teeth_contact": self._add_parameter(wall_layout, "Contatto denti (mm)", 0.3, 0.05, 5.0, 2, help_key="teeth_contact"),
            "teeth_base": self._add_parameter(wall_layout, "Base denti (mm)", 1.0, 0.1, 10.0, 2, help_key="teeth_base"),
            "teeth_penetration": self._add_parameter(wall_layout, "Penetrazione denti (mm)", 0.1, 0.0, 2.0, 2, help_key="teeth_penetration"),
            "perforation_size": self._add_parameter(wall_layout, "Dimensione fori (mm)", 2.0, 0.2, 20.0, 2, help_key="perforation_size"),
            "perforation_web": self._add_parameter(wall_layout, "Ponte tra fori (mm)", 1.0, 0.1, 10.0, 2, help_key="perforation_web"),
            "solid_margin": self._add_parameter(wall_layout, "Margine pieno (mm)", 1.0, 0.0, 10.0, 2, help_key="solid_margin"),
            "fragmentation": self._add_parameter(
                wall_layout, "Frammentazione (mm, 0 = no)", 0.0, 0.0, 100.0, 1, help_key="fragmentation"
            ),
        })
        self.perforation = QtWidgets.QCheckBox("Perforazioni a rombo")
        self.perforation.setChecked(True)
        self.perforation.stateChanged.connect(self._support_settings_changed)
        wall_layout.addLayout(self._checkbox_with_help(self.perforation, "perforation"))
        params_layout.addWidget(self.wall_panel)

        # Parameters of the BCC lattice
        self.lattice_panel = QtWidgets.QWidget()
        lattice_layout = QtWidgets.QVBoxLayout(self.lattice_panel)
        lattice_layout.setContentsMargins(0, 0, 0, 0)
        lattice_layout.setSpacing(7)
        self.support_inputs.update({
            "width": self._add_parameter(lattice_layout, "Spessore asta (mm)", 0.4, 0.1, 20.0, 2, help_key="width"),
            "cell_size": self._add_parameter(lattice_layout, "Dimensione cella BCC (mm)", 5.0, 2.0, 20.0, 2, help_key="cell_size"),
            "border": self._add_parameter(lattice_layout, "Passo aste perimetrali (mm)", 3.0, 0.5, 20.0, 2, help_key="border"),
        })
        params_layout.addWidget(self.lattice_panel)
        self.use_skin = QtWidgets.QCheckBox("Bordo esterno")
        self.use_skin.setChecked(True)
        self.upper_teeth = QtWidgets.QCheckBox("Denti superiori")
        self.upper_teeth.setChecked(True)
        self.lower_teeth = QtWidgets.QCheckBox("Denti inferiori")
        self.lower_teeth.setChecked(True)
        for checkbox, help_key in (
            (self.use_skin, "use_skin"),
            (self.upper_teeth, "upper_teeth"),
            (self.lower_teeth, "lower_teeth"),
        ):
            checkbox.stateChanged.connect(self._support_settings_changed)
            params_layout.addLayout(self._checkbox_with_help(checkbox, help_key))
        self.structure_controls = [self.use_skin, self.upper_teeth, self.lower_teeth]

        self.generate_button = QtWidgets.QPushButton("Genera supporti PySLM")
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.clicked.connect(self._generate_supports)
        right_layout.addWidget(self.generate_button)
        self.support_label = self._value_label("Nessun supporto generato")
        self.support_label.setWordWrap(True)
        right_layout.addWidget(self.support_label)
        right_layout.addWidget(QtWidgets.QLabel("REGIONI GENERATE"))
        self.support_region_list = QtWidgets.QListWidget()
        self.support_region_list.setMinimumHeight(90)
        self.support_region_list.setMaximumHeight(160)
        self.support_region_list.setToolTip(
            "Selezionare una regione per evidenziarla in azzurro intenso nel viewer."
        )
        right_layout.addWidget(self.support_region_list)
        self.remove_support_button = QtWidgets.QPushButton(
            "Rimuovi regione selezionata"
        )
        self.remove_support_button.setEnabled(False)
        self.remove_support_button.clicked.connect(self._remove_selected_support)
        self.support_region_list.currentRowChanged.connect(
            self._support_selection_changed
        )
        right_layout.addWidget(self.remove_support_button)
        self.restore_support_button = QtWidgets.QPushButton(
            "Ripristina ultima rimozione"
        )
        self.restore_support_button.setEnabled(False)
        self.restore_support_button.clicked.connect(self._restore_last_support)
        right_layout.addWidget(self.restore_support_button)
        right_layout.addStretch(1)
        self._support_type_changed()

        layout.addWidget(self._scrollable(self.left_panel, 290, 350))
        layout.addWidget(viewer_panel, 1)
        layout.addWidget(self._scrollable(self.right_panel, 320, 390))
        self.setCentralWidget(outer)

    def _build_diagnostics(self) -> None:
        dock = QtWidgets.QDockWidget("Diagnostica", self)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable)
        self.diagnostics = QtWidgets.QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumBlockCount(500)
        self.geometry_diagnostics = QtWidgets.QPlainTextEdit()
        self.geometry_diagnostics.setReadOnly(True)
        self.geometry_diagnostics.setPlainText(
            "Importare un componente e avviare la diagnostica geometrica.\n"
            "I candidati a cavità sono identificabili solo quando l'STL "
            "contiene gusci interni chiusi e correttamente orientati."
        )
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.diagnostics, "Eventi")
        tabs.addTab(self.geometry_diagnostics, "Geometria")
        dock.setMinimumHeight(125)
        dock.setWidget(tabs)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)
        # Keep the log compact so the 3D view gets the space (scrollable side panels no longer force it)
        self.resizeDocks([dock], [150], QtCore.Qt.Vertical)

    def _apply_style(self) -> None:
        self.apply_theme(DEFAULT_THEME)

    def apply_theme(self, name: str) -> None:
        """Apply one of the colour themes in :mod:`pyslm_app.themes`."""
        theme = THEMES[name]
        self.theme = theme
        self.setStyleSheet(stylesheet(theme))
        self.viewer.set_theme_colors(theme.viewer, theme.grid)
        for widget in self.findChildren(QtWidgets.QWidget):
            if widget.objectName() in ("sectionTitle", "collapseHeader"):
                original = widget.property("titleText")
                self._set_title_text(widget, original if original else widget.text())

    def _set_title_text(self, widget: Any, text: str) -> None:
        """Show a section title in capitals, or in sentence case for the Apple-like theme."""
        widget.setProperty("titleText", text)
        theme = getattr(self, "theme", None)
        widget.setText(_sentence_case(text) if theme is not None and theme.style == "apple" else text)

    def _choose_stl(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Apri componente STL", "", "Mesh STL (*.stl)"
        )
        if file_path:
            self._run_action("Importazione STL", lambda: self._load_stl(file_path))

    def _load_stl(self, file_path: str) -> None:
        extents = self.session.load_stl(file_path)
        self._internal_void_mesh = None
        self._probe_blocked_mesh = None
        self._clear_orientation_candidates()
        self._refresh_support_region_list()
        self.geometry_diagnostics.clear()
        self._set_orientation_inputs((0.0, 0.0, 0.0))
        self._refresh_analysis()
        self.file_label.setText(Path(file_path).name)
        self.statusBar().showMessage(f"Caricato: {Path(file_path).name}")
        self._log(
            f"STL importato con PySLM. Estensioni (X/Y/Z): "
            f"{extents[0]:.3f} x {extents[1]:.3f} x {extents[2]:.3f} mm."
        )

    def _apply_orientation(self, _value: Optional[float] = None) -> None:
        if self._updating_orientation or not self.session.has_part:
            return
        angles = [spin.value() for spin in self.rotation_inputs]
        self._run_action("Aggiornamento orientamento", lambda: self._set_orientation(angles))

    def _set_orientation(self, angles: List[float]) -> None:
        self.session.set_orientation(*angles)
        self._internal_void_mesh = None
        self._probe_blocked_mesh = None
        self._refresh_support_region_list()
        self._refresh_analysis()
        self.overhang_label.setText("Ricalcolare le superfici per l'orientamento corrente.")
        self.support_label.setText("Supporti invalidati: è cambiato l'orientamento.")
        self._log(f"Orientamento aggiornato: X {angles[0]:.1f}°, Y {angles[1]:.1f}°, Z {angles[2]:.1f}°.")

    def _apply_build_lift(self, value: float) -> None:
        if not self.session.has_part:
            self.session.build_lift = float(value)
            return

        def apply() -> None:
            self.session.set_build_lift(value)
            self._refresh_support_region_list()
            self._refresh_analysis()
            self.overhang_label.setText("Ricalcolare le superfici per la nuova posizione.")
            self.support_label.setText("Supporti invalidati: è cambiato il sollevamento.")
            self._log(f"Sollevamento dal piatto: {value:.2f} mm.")

        self._run_action("Aggiornamento sollevamento", apply)

    def _set_orientation_inputs(self, angles: Tuple[float, float, float]) -> None:
        self._updating_orientation = True
        try:
            for spin, value in zip(self.rotation_inputs, angles):
                spin.setValue(value)
        finally:
            self._updating_orientation = False

    def _compare_orientations(self) -> None:
        if not self.session.has_part:
            self._warn("Importare prima un componente STL.")
            return

        def compare() -> None:
            candidates = self.session.compare_orthogonal_orientations(
                self.angle_input.value()
            )
            self.orientation_candidates = candidates
            self.orientation_results.clear()
            for index, candidate in enumerate(candidates, start=1):
                x, y, z = candidate.rotation
                self.orientation_results.addItem(
                    f"{index:02d}  X{x:.0f} Y{y:.0f} Z{z:.0f}°"
                    f"  ·  costo {candidate.support_moment_area:.1f} mm³"
                    f"  ·  altezza {candidate.build_height:.1f} mm"
                )
            self.orientation_results.setCurrentRow(0)
            self.apply_orientation_button.setEnabled(bool(candidates))
            if candidates:
                first = candidates[0]
                self._log(
                    "Confrontati 24 orientamenti ortogonali con la metrica preliminare "
                    f"PySLM: minimo stimato {first.support_moment_area:.1f} mm³ "
                    f"(X/Y/Z {first.rotation[0]:.0f}/{first.rotation[1]:.0f}/"
                    f"{first.rotation[2]:.0f}°). Il risultato non considera "
                    "auto-intersezioni o generazione effettiva dei supporti."
                )

        self._run_action("Confronto orientamenti PySLM", compare)

    def _apply_selected_orientation(self) -> None:
        row = self.orientation_results.currentRow()
        if row < 0 or row >= len(self.orientation_candidates):
            self._warn("Selezionare un orientamento dalla lista.")
            return

        rotation = self.orientation_candidates[row].rotation
        self._set_orientation_inputs(rotation)
        self._set_orientation(list(rotation))

    def _clear_orientation_candidates(self) -> None:
        self.orientation_candidates = []
        self.orientation_results.clear()
        self.apply_orientation_button.setEnabled(False)

    def _support_settings_changed(self, _value: Optional[Any] = None) -> None:
        if not self.session.has_part:
            return
        self.session.clear_supports()
        self._refresh_support_region_list()
        self._refresh_viewer()
        self.support_label.setText("Parametri modificati: rigenerare i supporti.")
        if self.sender() is self.angle_input:
            self._clear_orientation_candidates()
            self.session.overhang_mesh = None
            self._analyze_overhangs()

    def _analyze_overhangs(self) -> None:
        if not self.session.has_part:
            self._warn("Importare prima un componente STL.")
            return

        def analyze() -> None:
            mesh = self.session.analyze_overhangs(self.angle_input.value())
            faces = len(mesh.faces)
            area = float(mesh.area) if faces else 0.0
            self.overhang_label.setText(f"{faces:,} facce · area superficiale {area:.2f} mm²")
            self._refresh_viewer()
            self._log(f"Analisi PySLM completata: {faces:,} facce oltre la soglia impostata.")

        self._run_action("Analisi overhang PySLM", analyze)

    def _analyze_mesh(self) -> None:
        if not self.session.has_part:
            self._warn("Importare prima un componente STL.")
            return

        def analyze() -> None:
            result = self.session.analyze_mesh()
            candidate_volume = sum(
                candidate.volume for candidate in result.enclosed_shell_candidates
            )
            cavity_lines = [
                f"Candidati gusci interni chiusi: "
                f"{len(result.enclosed_shell_candidates)}",
            ]
            cavity_lines.extend(
                f"  Candidato {index}: volume racchiuso circa "
                f"{candidate.volume:.3f} mm³"
                for index, candidate in enumerate(
                    result.enclosed_shell_candidates, start=1
                )
            )
            if not result.enclosed_shell_candidates:
                cavity_lines.append(
                    "Nessun guscio interno chiuso rilevato; questo non prova "
                    "l'assenza di cavità o canali interni."
                )
            self.geometry_diagnostics.setPlainText(
                "\n".join(
                    [
                        f"Triangoli: {result.triangle_count:,}",
                        f"Componenti connesse: {result.body_count}",
                        f"Mesh chiusa (watertight): {'sì' if result.watertight else 'no'}",
                        f"Orientamento facce coerente: "
                        f"{'sì' if result.winding_consistent else 'no'}",
                        f"Volume solido valido: {'sì' if result.valid_volume else 'no'}",
                        f"Numero di Eulero: {result.euler_number}",
                        f"Facce degeneri: {result.degenerate_face_count:,}",
                        *cavity_lines,
                        (
                            "Volume complessivo dei gusci candidati: "
                            f"{candidate_volume:.3f} mm³"
                        ),
                        "",
                        "Limite: l'analisi individua solo gusci chiusi interni "
                        "separati e orientati verso l'interno. Non verifica "
                        "cavità connesse alla superficie, diametri dei canali, "
                        "accessibilità o evacuazione della polvere."
                    ]
                )
            )
            self._log(
                f"Diagnostica mesh: {result.triangle_count:,} triangoli, "
                f"{result.body_count} componenti, "
                f"{len(result.enclosed_shell_candidates)} gusci interni candidati."
            )

        self._run_action("Diagnostica geometrica", analyze)

    def _screen_internal_voids(self) -> None:
        if not self.session.has_part:
            self._warn("Importare prima un componente STL.")
            return

        def screen() -> None:
            result = self.session.screen_internal_voids(
                self.void_pitch_input.value(),
                self.probe_diameter_input.value(),
            )
            self._internal_void_mesh = result.visualization_mesh
            self._probe_blocked_mesh = result.probe_blocked_visualization_mesh
            self._refresh_viewer()
            lines = [
                f"Orientamento corrente X/Y/Z: "
                f"{result.build_rotation[0]:.1f}° / "
                f"{result.build_rotation[1]:.1f}° / "
                f"{result.build_rotation[2]:.1f}°",
                f"Screen voxel: passo {result.voxel_pitch:.3f} mm",
                f"Diametro sonda sferica di prova: "
                f"{result.probe_diameter:.3f} mm",
                "Legenda viewer: ambra = cavità voxel; rosso = spazio-centro "
                "sonda non connesso all'esterno.",
                f"Griglia: {result.grid_shape[0]} x {result.grid_shape[1]} x "
                f"{result.grid_shape[2]} ({result.sampled_voxel_count:,} campioni)",
                "Volumi interni non connessi all'esterno nel reticolo: "
                f"{len(result.candidates)}",
            ]
            for index, candidate in enumerate(result.candidates[:10], start=1):
                lines.append(
                    f"  Candidato {index}: circa {candidate.volume:.3f} mm³, "
                    f"{candidate.voxel_count:,} voxel, limiti {candidate.bounds}"
                )
            if len(result.candidates) > 10:
                lines.append(
                    f"  Altri {len(result.candidates) - 10} candidati non mostrati."
                )
            if not result.candidates:
                lines.append(
                    "Nessun volume isolato rilevato a questa risoluzione; "
                    "non prova che tutte le cavità siano accessibili."
                )
            lines.append(
                "Componenti dello spazio dei centri sonda non connesse "
                "all'esterno: "
                f"{len(result.probe_blocked_candidates)}"
            )
            for index, candidate in enumerate(
                result.probe_blocked_candidates[:10], start=1
            ):
                lines.append(
                    f"  Zona non accessibile {index}: circa "
                    f"{candidate.volume:.3f} mm³ di spazio-centro, "
                    f"{candidate.voxel_count:,} voxel, limiti {candidate.bounds}"
                )
            if len(result.probe_blocked_candidates) > 10:
                lines.append(
                    "  Altre zone non accessibili non mostrate."
                )
            lines.extend(
                [
                    "",
                    "Volumi indicati per le zone sonda sono spazio disponibile "
                    "al centro della sfera, non volumi di cavità. "
                    "Stima voxel conservativa con connettività per faccia. "
                    "Passaggi prossimi alla risoluzione possono apparire chiusi; "
                    "il volume della sonda è sferico e non modella particelle reali. "
                    "Non valuta gravità, forma/dinamica della polvere, supporti "
                    "intrappolati o evacuazione effettiva.",
                ]
            )
            self.geometry_diagnostics.setPlainText("\n".join(lines))
            self._log(
                f"Screen cavità completato a {result.voxel_pitch:.3f} mm: "
                f"orientamento X/Y/Z {result.build_rotation[0]:.1f}/"
                f"{result.build_rotation[1]:.1f}/{result.build_rotation[2]:.1f}°, "
                f"{len(result.candidates)} volumi isolati e "
                f"{len(result.probe_blocked_candidates)} zone senza percorso "
                f"per la sonda da {result.probe_diameter:.3f} mm. "
                "Il risultato è una stima voxel, non una verifica di evacuabilità."
            )

        self._run_action("Screen cavità voxel", screen)

    def _void_screen_settings_changed(self, _value: Optional[float] = None) -> None:
        if self._internal_void_mesh is None and self._probe_blocked_mesh is None:
            return
        self._internal_void_mesh = None
        self._probe_blocked_mesh = None
        self._refresh_viewer()
        self.geometry_diagnostics.setPlainText(
            "I parametri dello screening sono cambiati. "
            "Eseguire di nuovo lo screen cavità per aggiornare il viewer."
        )
        self._log(
            "Overlay cavità rimossi: modificati passo voxel o diametro sonda. "
            "Rieseguire lo screening per aggiornare i risultati."
        )

    def _generate_supports(self) -> None:
        if not self.session.has_part:
            self._warn("Importare prima un componente STL.")
            return
        if self._support_thread is not None:
            return

        values = self.support_inputs
        support_type = self.support_type.currentData()
        try:
            wall_parameters = self._wall_parameters() if support_type == "walls" else None
            if wall_parameters is not None:
                wall_parameters.validate()
        except ValueError as error:
            self._warn(f"Parametri delle pareti non validi.\n\n{error}")
            return

        # Read every setting on the GUI thread; the worker must not touch widgets
        arguments = (
            support_type,
            self.angle_input.value(),
            values["ray"].value(),
            values["outer_gap"].value(),
            values["inner_gap"].value(),
            values["simplify"].value(),
            values["area"].value(),
            1.0,
            values["width"].value(),
            values["cell_size"].value(),
            values["border"].value(),
            self.use_skin.isChecked(),
            self.upper_teeth.isChecked(),
            self.lower_teeth.isChecked(),
        )
        session = self.session

        def identify(progress: Callable[[float], None]) -> List[Any]:
            return session.identify_support_regions(
                *arguments, wall_parameters=wall_parameters, progress=progress
            )

        thread = QtCore.QThread(self)
        worker = _SupportGeometryWorker(identify)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.identified.connect(
            lambda count: self._log(f"Regioni di supporto individuate: {count}.")
        )
        worker.progress.connect(self._support_build_progress)
        worker.finished.connect(
            lambda generated, meshes: self._support_build_finished(support_type, generated, meshes)
        )
        worker.failed.connect(self._support_build_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._support_thread_finished)
        self._support_thread = thread
        self._support_worker = worker
        self._set_busy(True)
        self._show_progress(0, "Identificazione regioni di supporto")
        thread.start()

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.left_panel, self.right_panel, self._toolbar):
            widget.setEnabled(not busy)
        if busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.BusyCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _support_build_progress(self, percent: int, message: str) -> None:
        self._show_progress(percent, message)

    def _show_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        self.progress_bar.setVisible(True)
        self.statusBar().showMessage(f"{message}…")

    def _support_build_finished(self, support_type: str, generated: list, meshes: list) -> None:
        self.session.apply_generated_supports(generated, meshes)
        self._refresh_support_region_list()
        count = len(self.session.support_regions)
        face_count = sum(len(mesh.faces) for mesh in self.session.support_meshes)
        support_name = {
            "walls": "a pareti",
            "grid_truss": "reticolo BCC 3D",
        }.get(support_type, "a blocco")
        self.support_label.setText(
            f"{support_name}: {count} regioni · "
            f"{len(self.session.support_meshes)} mesh · {face_count:,} facce"
        )
        self._refresh_viewer()
        self._log(
            f"PySLM ha generato {count} regioni {support_name}. "
            "I parametri modificati richiedono una nuova generazione."
        )
        if count == 0:
            self._log("Nessun supporto: verificare soglia overhang, area minima e geometria.")
        self.statusBar().showMessage("Generazione supporti PySLM: completata", 5000)

    def _support_build_failed(self, message: str) -> None:
        self.statusBar().showMessage("Generazione supporti PySLM: errore", 8000)
        self._log(f"ERRORE — Generazione supporti PySLM: {message}")
        self._warn(f"Generazione supporti PySLM non riuscita.\n\n{message}")

    def _support_thread_finished(self) -> None:
        self.progress_bar.setVisible(False)
        self._set_busy(False)
        if self._support_thread is not None:
            self._support_thread.deleteLater()
        if self._support_worker is not None:
            self._support_worker.deleteLater()
        self._support_thread = None
        self._support_worker = None

    def closeEvent(self, event: Any) -> None:
        if self._support_thread is not None:
            # The geometry build cannot be interrupted safely; wait for it so
            # the worker thread is not destroyed while it is still running.
            self.statusBar().showMessage("Attendere il completamento della generazione supporti…")
            self._support_thread.wait()
        super().closeEvent(event)

    def _remove_selected_support(self) -> None:
        index = self.support_region_list.currentRow()
        if index < 0:
            self._warn("Selezionare una regione di supporto da rimuovere.")
            return

        def remove() -> None:
            self.session.remove_support_region(index)
            self._refresh_support_region_list()
            self._refresh_viewer()
            face_count = sum(len(mesh.faces) for mesh in self.session.support_meshes)
            self.support_label.setText(
                f"{len(self.session.support_regions)} regioni rimanenti · "
                f"{face_count:,} facce"
            )
            self._log(
                f"Rimossa la regione di supporto {index + 1}. "
                "L'export includerà solo le regioni rimaste."
            )

        self._run_action("Rimozione regione supporto", remove)

    def _refresh_support_region_list(self) -> None:
        self.support_region_list.blockSignals(True)
        try:
            self.support_region_list.clear()
            for index, (region, mesh) in enumerate(
                zip(self.session.support_regions, self.session.support_meshes),
                start=1,
            ):
                surface = region.supportSurface
                surface_area = float(surface.area) if surface is not None else 0.0
                self.support_region_list.addItem(
                    f"Supporto {index} · {len(mesh.faces):,} facce · "
                    f"superficie {surface_area:.2f} mm²"
                )
        finally:
            self.support_region_list.blockSignals(False)
        self.remove_support_button.setEnabled(
            self.support_region_list.currentRow() >= 0
        )
        self.restore_support_button.setEnabled(
            self.session.can_restore_support_region
        )

    def _support_selection_changed(self, row: int) -> None:
        self.remove_support_button.setEnabled(row >= 0)
        self.viewer.set_selected_support(row if row >= 0 else None)

    def _current_support_index(self) -> Optional[int]:
        row = self.support_region_list.currentRow()
        if 0 <= row < len(self.session.support_meshes):
            return row
        return None

    def _restore_last_support(self) -> None:
        if not self.session.can_restore_support_region:
            self._warn("Non ci sono regioni rimosse da ripristinare.")
            return

        def restore() -> None:
            index = self.session.restore_last_removed_support_region()
            self._refresh_support_region_list()
            self._refresh_viewer()
            self.support_region_list.setCurrentRow(index)
            face_count = sum(len(mesh.faces) for mesh in self.session.support_meshes)
            self.support_label.setText(
                f"{len(self.session.support_regions)} regioni · "
                f"{face_count:,} facce"
            )
            self._log(
                f"Ripristinata la regione di supporto {index + 1}; "
                "gli export includeranno nuovamente questa mesh."
            )

        self._run_action("Ripristino regione supporto", restore)

    def _toggle_support_parameters(self, expanded: bool) -> None:
        self.support_heading.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        self.support_params_panel.setVisible(expanded)

    def _support_type_changed(self, _index: Optional[int] = None) -> None:
        support_type = self.support_type.currentData()
        self._set_title_text(
            self.support_heading,
            {
                "walls": "PARAMETRI BLOCCO A PARETI",
                "grid_truss": "PARAMETRI RETICOLO BCC 3D",
            }.get(support_type, "PARAMETRI SUPPORTO A BLOCCO"),
        )
        self.wall_panel.setVisible(support_type == "walls")
        self.lattice_panel.setVisible(support_type == "grid_truss")
        self.use_skin.setEnabled(support_type in ("walls", "grid_truss"))
        # Teeth are only generated by the wall supports
        for control in (self.upper_teeth, self.lower_teeth):
            control.setEnabled(support_type == "walls")
        self._support_settings_changed()

    def _wall_parameters(self) -> Any:
        from pyslm.support import WallSupportParameters

        values = self.support_inputs
        return WallSupportParameters(
            hatchSpacing=values["wall_spacing"].value(),
            wallThickness=values["wall_thickness"].value(),
            teethHeight=values["teeth_height"].value(),
            teethTopLength=values["teeth_contact"].value(),
            teethBaseLength=values["teeth_base"].value(),
            teethPenetration=values["teeth_penetration"].value(),
            usePerforation=self.perforation.isChecked(),
            perforationSize=values["perforation_size"].value(),
            perforationWeb=values["perforation_web"].value(),
            perforationMargin=values["solid_margin"].value(),
            fragmentationInterval=values["fragmentation"].value(),
        )

    def _export_part(self) -> None:
        self._export_with_dialog("Esporta componente orientato", self.session.export_part)

    def _export_supports(self) -> None:
        self._export_with_dialog("Esporta supporti BCC 3D", self.session.export_supports)

    def _export_assembly(self) -> None:
        self._export_with_dialog("Esporta componente e supporti", self.session.export_assembly)

    def _export_with_dialog(self, title: str, operation: Callable[[str], None]) -> None:
        if not self.session.has_part:
            self._warn("Importare prima un componente STL.")
            return
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, title, "", "Mesh STL (*.stl)"
        )
        if file_path:
            if not file_path.lower().endswith(".stl"):
                file_path += ".stl"
            self._run_action(title, lambda: operation(file_path))

    def _refresh_analysis(self) -> None:
        if not self.session.has_part:
            return
        self._refresh_viewer()
        self._update_metrics()
        self.overhang_label.setText("Superfici critiche: —")

    def _refresh_viewer(self) -> None:
        if not self.session.has_part:
            return
        self.viewer.show_meshes(
            self.session.part.geometry,
            self.session.overhang_mesh,
            self.session.support_meshes,
            self._current_support_index(),
            internal_voids=self._internal_void_mesh,
            probe_blocked_regions=self._probe_blocked_mesh,
        )
        # The shown meshes (and their extent) changed: re-apply the section to them
        self._update_section()

    def _update_section(self, _value: Optional[Any] = None) -> None:
        enabled = self.section_check.isChecked()
        for widget in (self.section_axis, self.section_slider, self.section_flip):
            widget.setEnabled(enabled)
        bounds = self.viewer.scene_bounds
        if not enabled or bounds is None:
            self.viewer.clear_section()
            self.section_label.setText("—")
            return
        axis = self.section_axis.currentData()
        index = "xyz".index(axis)
        low, high = float(bounds[0, index]), float(bounds[1, index])
        position = low + (high - low) * self.section_slider.value() / self.section_slider.maximum()
        self.viewer.set_section(axis, position, self.section_flip.isChecked())
        self.section_label.setText(f"{axis.upper()} = {position:.2f} mm")

    def _set_viewer_brightness(self, value: int) -> None:
        self.brightness_value_label.setText(f"{value}%")
        self.viewer.set_brightness(value)

    def _material_selected(self, _index: int) -> None:
        density = self.material_input.currentData()
        if density is not None:
            self.density_input.setValue(float(density))

    def _density_edited(self, value: float) -> None:
        # A density typed or changed with the arrows no longer matches the chosen material
        density = self.material_input.currentData()
        if density is not None and abs(float(density) - value) > 1e-9:
            self.material_input.blockSignals(True)
            self.material_input.setCurrentIndex(self.material_input.count() - 1)
            self.material_input.blockSignals(False)

    def _update_metrics(self, _value: Optional[float] = None) -> None:
        if not self.session.has_part:
            return
        extents, volume = self.session.get_metrics()
        self.geometry_label.setText(
            f"Dimensioni: {extents[0]:.2f} x {extents[1]:.2f} x {extents[2]:.2f} mm"
        )
        if volume is None:
            self.volume_label.setText("Volume: non disponibile (mesh non valida/chiusa)")
            self.mass_label.setText("Peso teorico: non calcolabile")
            self._log("Volume non disponibile: PySLM richiede una mesh chiusa valida.")
        else:
            self.volume_label.setText(f"Volume: {volume:.2f} mm³")
            mass = volume / 1000.0 * self.density_input.value()
            self.mass_label.setText(f"Peso teorico: {mass:.3f} g")

    def _run_action(self, label: str, operation: Callable[[], None]) -> bool:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.statusBar().showMessage(f"{label}…")
        QtWidgets.QApplication.processEvents()
        try:
            operation()
            self.statusBar().showMessage(f"{label}: completata", 5000)
            return True
        except Exception as error:
            logging.exception("%s non riuscita", label)
            self.statusBar().showMessage(f"{label}: errore", 8000)
            self._log(f"ERRORE — {label}: {error}")
            self._warn(f"{label} non riuscita.\n\n{error}")
            return False
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _warn(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "PySLM Desktop", message)

    def _log(self, message: str) -> None:
        self.diagnostics.appendPlainText(message)

    @staticmethod
    def _section_title(text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    @staticmethod
    def _value_label(text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("valueLabel")
        return label

    @staticmethod
    def _double_input(value: float, minimum: float, maximum: float, decimals: int) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(value)
        # A compact fixed width leaves the rest of the row to the label and its "?"
        spin.setFixedWidth(88)
        return spin

    def _add_parameter(
        self,
        layout: QtWidgets.QVBoxLayout,
        title: str,
        value: float,
        minimum: float,
        maximum: float,
        decimals: int,
        help_key: Optional[str] = None,
    ) -> QtWidgets.QDoubleSpinBox:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(title))
        spin = self._double_input(value, minimum, maximum, decimals)
        spin.valueChanged.connect(self._support_settings_changed)
        if help_key is not None:
            row.addWidget(self._help_badge(help_key, spin))
        row.addWidget(spin)
        layout.addLayout(row)
        return spin

    def _help_badge(self, help_key: str, *targets: QtWidgets.QWidget) -> "_HelpBadge":
        """A "?" explaining ``help_key``; the controls it describes show the same tooltip."""
        text = HELP[help_key]
        badge = _HelpBadge(text)
        for target in targets:
            target.setToolTip(_tooltip_html(text))
        self.help_badges[help_key] = badge
        return badge

    def _labelled_with_help(self, text: str, help_key: str, *targets: QtWidgets.QWidget) -> QtWidgets.QHBoxLayout:
        """A label followed by its "?" badge."""
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QtWidgets.QLabel(text))
        row.addWidget(self._help_badge(help_key, *targets))
        row.addStretch(1)
        return row

    def _checkbox_with_help(self, checkbox: QtWidgets.QCheckBox, help_key: str) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(checkbox)
        row.addWidget(self._help_badge(help_key, checkbox))
        row.addStretch(1)
        return row

    def _title_with_help(self, text: str, help_key: str, *targets: QtWidgets.QWidget) -> QtWidgets.QWidget:
        """A section title with one "?" that explains the whole group."""
        container = QtWidgets.QWidget()
        container.setObjectName("titleRow")
        row = QtWidgets.QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self._section_title(text), 1)
        row.addWidget(self._help_badge(help_key, *targets))
        return container

    @staticmethod
    def _scrollable(panel: QtWidgets.QWidget, minimum: int, maximum: int) -> QtWidgets.QScrollArea:
        """Wrap a side panel in a vertical scroll area so long parameter lists stay reachable."""
        area = QtWidgets.QScrollArea()
        area.setObjectName("sideScroll")
        area.setWidget(panel)
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        area.setMinimumWidth(minimum)
        area.setMaximumWidth(maximum)
        return area


def main() -> int:
    log_path = Path(__file__).resolve().parents[1] / "pyslm-support-debug.log"
    handlers: List[logging.Handler] = [
        logging.FileHandler(log_path, mode="w", encoding="utf-8")
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.captureWarnings(True)
    logging.info("Log debug completo: %s", log_path)
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
