PySLM Desktop
=============

The repository includes an initial desktop application for preparing a single
STL part with PySLM. This first version supports STL import, interactive 3D
viewing, XYZ orientation, overhang visualization, PySLM block and grid-truss
support generation, comparison of 24 distinct orthogonal build orientations,
and STL export of the oriented part, supports, or their combined mesh.

Install the desktop and support-generation dependencies from the repository
root with Python 3.14, then launch the application:

.. code-block:: console

   py -3.14 -m pip install -e ".[desktop,triangulation]"
   pyslm-desktop

The ``triangulation`` extra is needed for block and grid-truss support
generation. If you only need STL viewing and mesh analysis, install
``.[desktop]`` instead.
On Windows, installing ``triangle`` may require Microsoft C++ Build Tools
14 or newer. The application reports this requirement if support generation is
attempted without the triangulation backend.

STL files do not encode physical units. The application treats input coordinates
as millimetres. The displayed mass is an estimate based on the entered density
(default: 7.85 g/cm³) and is shown only when PySLM can calculate a valid volume
for the mesh. Set a density appropriate to the actual alloy before relying on
the estimate.

The viewer renders the part and overhangs as opaque shaded surfaces. Part
normals are corrected on a display-only copy, leaving the geometry used for
analysis and export unchanged. The internal-void screen intentionally makes the
part translucent so its resolution-limited cavity overlays can be inspected.

The support panel offers the block and grid-truss generators implemented by
:class:`pyslm.support.BlockSupportGenerator` and
:class:`pyslm.support.GridBlockSupportGenerator`. Grid-only parameters are
disabled when block support is selected. Generated geometry is produced by
PySLM's support-region ``geometry()`` methods. Support generation depends on
the optional boolean-geometry dependencies installed by the ``desktop`` extra;
support height maps are projected on the CPU, so generation runs in the
background and does not interfere with the OpenGL 3D viewer. PySLM errors are reported in the application's diagnostics
panel and do not terminate the window. Block and grid-truss generation also
requires the optional ``triangle`` backend from the ``triangulation`` extra.
Individual generated regions can be
removed from the support list; subsequent support and assembly exports use
only the remaining regions. The last removal can be undone; changing the part
or support settings clears the removed-region history. Selecting a generated
region highlights it in the viewer; this helps inspect regions before removal
but does not alter PySLM's generated geometry.

Every adjustable parameter has a "?" beside its name (one shared "?" for the
orientation, cavity-screen and section groups): hovering it explains what it does. While supports are generated, the status bar shows the overall
progress as a percentage.

The "Sezione" controls above the 3D view cut the part and the supports with a
plane along X, Y or Z; the slider moves the plane between the extremes of the
scene, and "Inverti lato" hides the other half. The cut faces of closed solids
are shown filled (brick red for the part, a darker shade for supports), so wall
thicknesses, internal cavities and support contacts are visible. The section
only changes the display, never the geometry or the exported files.

The default support type, "Blocco a pareti (stile SLM)", follows the block
supports of commercial SLM build-preparation software. Each support region is
filled with thin vertical walls on an X/Y grid ("Passo pareti") plus a wall
along the region boundary ("Bordo esterno"). Every wall runs from the build
plate or the part up to the overhang and has a real thickness ("Spessore
parete"), so the exported STL contains closed solids. Trapezoidal teeth touch
the part: "Altezza denti", "Contatto denti" (tip length), "Base denti" and
"Penetrazione denti" (how far the tips enter the part). Lower teeth are only
used where a wall stands on the part, never on the build plate. Diamond
perforations ("Dimensione fori", with "Ponte tra fori" of material between
them) lighten the walls and can be disabled. "Margine pieno" is the solid band
kept without holes below the upper teeth and above the base; very low regions
may stay solid unless it is reduced. The boundary wall is perforated
continuously around corners and curves, and
"Frammentazione" splits the walls at a fixed interval (0 disables it).

"Sollevamento piatto" raises the part above the build plate (default 3 mm).
Without it, downward-facing surfaces at the bottom of the part rest on the
plate and cannot receive supports.

The BCC lattice option builds a conformal lattice of vertical pillars. Each
pillar runs from the lower surface (build plate or part) to the overhang and is
braced to neighbouring pillars by BCC diagonals; diagonals that would leave the
support volume are discarded. "Dimensione cella BCC" sets the lattice cell size
and "Spessore asta" the strut diameter. "Genera bordo esterno a aste" adds a
braced wall of pillars along the support boundary, spaced by "Passo aste
perimetrali"; it also supports regions narrower than one cell. Very short
pillars where the overhang sits on the part (or regions thinner than the strut
radius) may remain unbraced, but every pillar is anchored at both ends. The
"Denti superiori/inferiori" options apply only to the legacy grid-truss skin
and have no effect on the BCC lattice.

Orientation ranking uses PySLM's ``approximateSupportMomentArea`` estimate and
uses projected overhang area and build height to break ties. PySLM documents
this metric as an initial estimate; it does not account for support
self-intersections. Compare candidates with actual generated supports before
selecting a production orientation.

On Windows, if ``pip`` needs to build the optional ``triangle`` triangulation
backend from source, Microsoft C++ Build Tools (MSVC 14 or newer) may be
required. PySLM is now certified for Python 3.14 in the project metadata and
CI matrix, while retaining compatibility with its existing Python 3.8+ floor.

On a desktop with a working OpenGL context, the real support-generation
integration test can be run with:

.. code-block:: console

   set PYSLM_RUN_SUPPORT_INTEGRATION=1
   py -3.14 -m pytest tests/test_desktop_services.py -q

The combined STL export concatenates the part and the PySLM support meshes; it
does not perform an additional Boolean union or mesh repair. Validate exported
files in the target manufacturing workflow before production use.

This is an initial workflow, not a complete build-preparation system. It does
not automatically apply an orientation or allow manual reshaping of support
geometry.

The geometry diagnostics report mesh closure, face winding, volume validity,
connected components, Euler number, and degenerate faces. A "cavity candidate"
is reported only for a closed inward-oriented mesh shell nested inside a larger
closed outward-oriented shell. This topological indicator is not a general
cavity detector.

The separate voxel screen transforms the original diagnostic STL using the
current PySLM part transform and samples the result at the selected pitch. It
reports free-space components that are not face-connected to the sampled
exterior. Their volumes and build-coordinate bounds are estimates at that
resolution. Narrow
openings can be missed, so an accessible cavity may be reported as isolated;
an optional spherical probe additionally screens for sampled center positions
with enough estimated clearance to pass. Components of this probe-center space
that are not connected to the sampled exterior are reported separately; their
volume is not the physical cavity volume. The clearance calculation is
conservative and voxel-based, with face-connected paths only. Neither screen
assesses support entrapment, accounts for build orientation or gravity, models
powder particles or their flow, or verifies powder evacuation. An empty result
is not proof that the part is evacuable. Review the geometry and validate
powder removal using the actual process and part orientation.

When internal void candidates are found, the application also displays a
marching-cubes surface of the sampled void voxels over a translucent part.
This is a visualization of the resolution-limited screen, not an exact CAD
cavity surface. The optional probe-disconnected center-space is overlaid in a
separate color to distinguish it from the full void candidate. Loading a new
part, changing its orientation, or editing the voxel pitch or probe diameter
clears the overlays; run the screen again to visualize the current settings
and pose.
