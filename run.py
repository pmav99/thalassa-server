from __future__ import annotations

import logging
import logging.config

import panel as pn
from holoviews import opts as hvopts
from ruamel.yaml import YAML

import seareport_server.ui

yaml = YAML(typ="safe", pure=True)

# configure logging
logger = logging.getLogger()

with open("config.yml", "rb") as fd:
    config = yaml.load(fd.read())

logging.config.dictConfig(config["logging"])
logger.debug(logging.getLogger("thalassa").handlers)

# load bokeh
# hv.extension("bokeh")
# pn.extension(sizing_mode="scale_width")

# pn.config.sizing_mode="fixed"
# pn.config.sizing_mode="stretch_width"
# pn.config.sizing_mode="scale_width"
# pn.config.frame_width=800
# pn.config.width_policy="fit"


# Set some defaults for the visualization of the graphs
hvopts.defaults(
    hvopts.Curve(
        height=300,
        responsive=True,
        # show_title=True,
        tools=["hover"],
        active_tools=["pan", "wheel_zoom"],
    ),
    hvopts.Image(
        height=500,
        responsive=True,
        # width_policy="max",
        # height_policy="max",
        # frame_width=1500,
        show_title=True,
        tools=["hover"],
        active_tools=["pan", "wheel_zoom"],
    ),
)


ui = seareport_server.ui.SeareportUI()

# https://panel.holoviz.org/reference/templates/Bootstrap.html
# template = pn.template.FastListTemplate(
# template = pn.template.ReactTemplate(
# template = pn.template.BootstrapTemplate(
template = pn.template.MaterialTemplate(
    # site="example.com",
    title="Seareport Server",
    # theme="dark",
    # logo="seareport_server/static/logo.png",
    # favicon="seareport_server/static/favicon.png",
    sidebar=[ui.sidebar],
    # sidebar_width=350,  # in pixels! must be an integer!
    # main_max_width="1350px", #  must be a string!
    main=[ui.main],
    # main_layout = "",
)

template.header_background = "#2A6589"

_ = template.servable()
