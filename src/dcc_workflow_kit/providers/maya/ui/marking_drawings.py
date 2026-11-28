# SPDX-License-Identifier: GPL-3.0-or-later
"""Kit-drawn pictures for marking menu items whose command is on no Maya menu item or shelf button with a picture
(#525): the component commands of the Shift+right-click menus (Extrude / Delete Edge, Extrude / Delete Vertex, Merge
Vertices, Merge Border Edges).

Drawn from scratch in the shelf's vocabulary (``shelf_icons``: poly modeling orange, dark outline, tool parts light
grey, hollow vertex squares, the action mark small in a corner), like ``menu_drawings``. ``marking/icon_data`` links
an item to ``("mark", name)``. Pure numpy, no bpy at import.
"""

from .menu_drawings_mesh import vsq
from .shelf_icons import DARK, LIGHT, ORANGE, Canvas, arrow, shade, xmark

DRAWINGS = {}       # name -> fn(cv)
GREYF = shade(LIGHT, -0.12)


def drawing(name):
    def deco(fn):
        DRAWINGS[name] = fn
        return fn
    return deco


def draw(name, size=32):
    """``size`` x ``size`` RGBA float32 (straight alpha, top row first) of drawing ``name``."""
    cv = Canvas(size)
    DRAWINGS[name](cv)
    return cv.result()


@drawing("Extrude Edge")
def d_extrude_edge(cv):
    cv.poly([(2, 27), (18, 27), (26, 20), (10, 20)], GREYF, ol=True)          # the face the edge borders
    cv.poly([(10, 20), (26, 20), (26, 9), (10, 9)], ORANGE, ol=True)           # the new face pulled from the edge
    cv.line((10, 20), (26, 20), 2.0, DARK)
    arrow(cv, (6, 18), (6, 4), w=2.2, head=4)


@drawing("Extrude Vertex")
def d_extrude_vertex(cv):
    cv.poly([(3, 26), (19, 30), (29, 22), (13, 18)], GREYF, ol=True)
    cv.poly([(13, 18), (16, 23), (19, 21), (17, 6)], ORANGE, ol=True)         # a spike pulled from the vertex
    vsq(cv, 17, 6, 2.4)
    vsq(cv, 16, 23, 2.0, DARK)
    arrow(cv, (6, 16), (6, 3), w=2.2, head=4)


@drawing("Delete Edge")
def d_delete_edge(cv):
    cv.line((5, 27), (20, 8), 2.6, ORANGE, ol=True)
    vsq(cv, 5, 27, 2.6, LIGHT)
    vsq(cv, 20, 8, 2.6, LIGHT)
    xmark(cv, 25, 24, s=4.5, w=2.6)


@drawing("Delete Vertex")
def d_delete_vertex(cv):
    for p in ((2, 14), (14, 2), (22, 22), (4, 28)):
        cv.line((13, 15), p, 1.4, LIGHT)
    vsq(cv, 13, 15, 3.4)
    xmark(cv, 25, 8, s=4.5, w=2.6)


@drawing("Merge Vertices")
def d_merge_vertices(cv):
    cv.line((3, 29), (16, 18), 1.4, LIGHT)
    cv.line((29, 29), (16, 18), 1.4, LIGHT)
    vsq(cv, 5, 6, 2.4, LIGHT)
    vsq(cv, 27, 6, 2.4, LIGHT)
    arrow(cv, (7, 8), (13, 14), w=1.8, head=3.5, ol=False)
    arrow(cv, (25, 8), (19, 14), w=1.8, head=3.5, ol=False)
    vsq(cv, 16, 18, 3.2)


@drawing("Merge Border Edges")
def d_merge_border_edges(cv):
    cv.poly([(1, 5), (9, 5), (9, 27), (1, 27)], ORANGE, ol=True)
    cv.poly([(23, 5), (31, 5), (31, 27), (23, 27)], ORANGE, ol=True)
    cv.line((9, 5), (9, 27), 2.0, LIGHT)
    cv.line((23, 5), (23, 27), 2.0, LIGHT)
    arrow(cv, (10, 16), (15.5, 16), w=2.0, head=4)
    arrow(cv, (22, 16), (16.5, 16), w=2.0, head=4)
