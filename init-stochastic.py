import tempfile
import os
import glob
import sys
import subprocess
from PySide2.QtWidgets import QMessageBox, QPushButton

import mari  # type: ignore

# files should be in ~/Mari/Scripts or %userprofile%/Documents/Mari/Scripts
EXE_GLOB = "precompute*"
XML_GLOB = "A_Stochastic.xml"

CATEGORY_NAME = "Precomp. Maps"
META_HASH = "precomp-hash"
META_TYPE = "precomp-type"
NODE_PATH = "Procedural/Pattern/Stochastic"


def precompute_selected_nodes():
    temp_dir = tempfile.gettempdir()
    nodeGraph = mari.geo.current().nodeGraph()
    selectedNodes = [
        n for n in nodeGraph.selectedNodeList() if "A_Stochastic" in n.nodeInformation()
    ]
    exe = search_script_path(EXE_GLOB)
    if not exe and precomp_exe_not_found() == QMessageBox.AcceptRole:
        exe = mari.utils.misc.getOpenFileName("Choose precompute executable", "Executable (*.exe)")
    if not exe:
        return

    for node in selectedNodes:
        input_img = node.metadataAsImage("Texture")
        if input_img is None:
            continue

        input_img_hash = input_img.hash()
        input_img_size = max(*input_img.size())

        already_completed_maps = [
            im
            for im in mari.images.list()
            if im.hasMetadata(META_HASH) and im.metadata(META_HASH) == input_img_hash
        ]
        if len(already_completed_maps) >= 2:
            img = next((i for i in already_completed_maps if i.metadata(META_TYPE) == "img"), None)
            lut = next((i for i in already_completed_maps if i.metadata(META_TYPE) == "lut"), None)
            if img and lut:
                set_stochastic_metadata(node, img, lut, input_img_size)
                continue

        input_path = os.path.join(temp_dir, os.path.basename(input_img.mostRelevantPath()))
        # FIXME: This overwrites the old most relevant path since it's the latest export. boo
        input_img.saveAs(input_path)

        (ret_code, (img_path, lut_path)) = call_precompute(exe, input_path, temp_dir)
        if ret_code != 0:
            message_box(
                "Precompute failed with code {}. Check mari logs for details.".format(ret_code)
            )
            return

        beforeLoadCategory = mari.images.currentCategory()
        mari.images.addCategory(CATEGORY_NAME)
        mari.images.selectCategory(CATEGORY_NAME)

        img_layers = mari.images.open(img_path, Config=mari.ColorspaceConfig(Scalar=True))
        lut_layers = mari.images.open(lut_path)

        if len(img_layers) == 0 or len(lut_layers) == 0:
            sys.stderr.write("ERROR: Precomputed images loaded from image manager with 0 layers\n")
            return
        if len(img_layers) > 1 or len(lut_layers) > 1:
            sys.stdout.write(
                "WARN: Precomputed images loaded with more than one layer. Only using first layer.\n"
            )
            return

        mari.images.selectCategory(beforeLoadCategory)

        img = img_layers[0]
        lut = lut_layers[0]
        img.setMetadata(META_TYPE, "img")
        lut.setMetadata(META_TYPE, "lut")
        img.setMetadata(META_HASH, input_img_hash)
        lut.setMetadata(META_HASH, input_img_hash)

        set_stochastic_metadata(node, img, lut, input_img_size)


def set_stochastic_metadata(node, img, lut, size):
    node.setMetadata("Tinput", img)
    node.setMetadata("Tinv", lut)
    node.setMetadata("Size", size)
    node.setMetadataDefault("Size", size)
    node.setMetadata("PreserveHistogram", True)


def call_precompute(exe_path, in_path, out_path):
    input_file_prefix, _ = os.path.splitext(os.path.basename(in_path))
    img_prefix = input_file_prefix + "-img"
    lut_prefix = input_file_prefix + "-lut"
    img_path = os.path.join(out_path, img_prefix + ".tif")
    lut_path = os.path.join(out_path, lut_prefix + ".tif")
    command = "{} --in-file {} --out-dir {} --img-prefix {} --lut-prefix {}".format(
        exe_path, in_path, out_path, img_prefix, lut_prefix
    )
    return subprocess.call(command), (
        img_path,
        lut_path,
    )


def search_script_path(glob_pattern):
    env = os.environ.get("MARI_SCRIPT_PATH")
    env_paths = env.split(os.pathsep) if env else []
    default_script_path = os.path.join(
        os.path.expanduser("~" if os.name == "posix" else os.path.join("~", "Documents")),
        "Mari",
        "Scripts",
    )

    dirs_to_search = ([default_script_path] if default_script_path else []) + env_paths + sys.path
    return next(
        (
            matches[0]
            for matches in (glob.glob(os.path.join(d, glob_pattern)) for d in dirs_to_search if d)
            if matches
        ),
        None,
    )


def message_box(msg, title="Error", accept_text="Ok", reject_text=""):
    box = QMessageBox()
    accept_button = QPushButton(accept_text)
    box.setIcon(QMessageBox.Information)
    box.setText(msg)
    box.setWindowTitle(title)
    box.addButton(accept_button, QMessageBox.AcceptRole)
    if reject_text:
        reject_button = QPushButton(reject_text)
        box.addButton(reject_button, QMessageBox.RejectRole)
    return box.exec_()


def precomp_exe_not_found():
    return message_box(
        r"""Precompute executable not found.
Download at: https://github.com/AliShazly/gaussian-histogram
You can place the file in any of the following directories:
    - $MARI_SCRIPT_PATH
    - ~/Mari/Scripts or %USERPROFILE%\Documents\Mari\Scripts
    - Anywhere in python's sys.path
You can also choose the executable file manually.
        """,
        title="Precompute executable not found",
        accept_text="Choose file",
        reject_text="Cancel",
    )


if __name__ == "__main__":
    xml_path = search_script_path(XML_GLOB)
    if xml_path:
        mari.gl_render.registerCustomNodeFromXMLFile(NODE_PATH, xml_path)
        action = mari.actions.create(
            "Stochastic/Precompute Selected", "precompute_selected_nodes()"
        )
        mari.menus.addAction(action, "NodeGraph/Context/Misc")
    else:
        sys.stderr.write("ERROR: Could not find stochastic node file\n")

    print("Stochastic node loaded successfully under {}".format(NODE_PATH))
