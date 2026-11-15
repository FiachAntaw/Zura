// Monitor tab for a Zortrax printer: live camera snapshot, status and controls.
// The Monitor stage loads this through a Loader, so the root must be a Component.
import QtQuick 2.15
import QtQuick.Layouts 1.15
import QtQuick.Controls 2.15
import UM 1.5 as UM
import Cura 1.0 as Cura

Component
{
    Rectangle
    {
        id: monitorFrame
        width: maximumWidth
        height: maximumHeight
        color: UM.Theme.getColor("monitor_stage_background")

        property var device: OutputDevice
        property var st: device ? device.zortraxStatus : ({})
        property bool reachable: device && device.lastError === ""
        property string state_: (st.printerStatus || "").toLowerCase()
        property bool printing: ["printing", "heating", "busy", "preparing_for_print"].indexOf(state_) >= 0
        property bool paused: state_ === "printing_paused" || state_ === "paused"
        property real progress: st.job_progress ? parseFloat(st.job_progress) : 0

        UM.I18nCatalog { id: catalog; name: "cura" }

        function stateText(s)
        {
            switch (s)
            {
                case "printing": return catalog.i18nc("@label:status", "Printing")
                case "heating": return catalog.i18nc("@label:status", "Heating")
                case "busy": case "preparing_for_print": case "initializing": return catalog.i18nc("@label:status", "Preparing")
                case "paused": case "printing_paused": return catalog.i18nc("@label:status", "Paused")
                case "waiting_for_material_setup": return catalog.i18nc("@label:status", "Waiting for material")
                case "idle": case "idling": return catalog.i18nc("@label:status", "Idle")
                case "sleep": case "sleeping": return catalog.i18nc("@label:status", "Sleeping")
                case "failsafe": return catalog.i18nc("@label:status", "Needs attention")
                case "": return catalog.i18nc("@label:status", "Connecting…")
                default: return s.charAt(0).toUpperCase() + s.slice(1)
            }
        }

        // Card
        Rectangle
        {
            id: card
            anchors.top: parent.top
            anchors.topMargin: 48 * screenScaleFactor
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(1000 * screenScaleFactor, parent.width - 2 * UM.Theme.getSize("wide_margin").width)
            height: content.height + 2 * UM.Theme.getSize("wide_margin").height
            color: UM.Theme.getColor("monitor_card_background")
            border.color: UM.Theme.getColor("monitor_card_border")
            border.width: UM.Theme.getSize("default_lining").width
            radius: UM.Theme.getSize("default_radius").width

            RowLayout
            {
                id: content
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: UM.Theme.getSize("wide_margin").width
                spacing: UM.Theme.getSize("wide_margin").width

                // Camera
                Rectangle
                {
                    Layout.preferredWidth: 480 * screenScaleFactor
                    Layout.preferredHeight: 360 * screenScaleFactor
                    color: UM.Theme.getColor("monitor_skeleton_loading")
                    radius: UM.Theme.getSize("default_radius").width
                    clip: true

                    Image
                    {
                        anchors.fill: parent
                        fillMode: Image.PreserveAspectCrop
                        cache: false
                        source: device ? device.cameraUrl : ""
                    }
                    UM.Label
                    {
                        anchors.centerIn: parent
                        visible: !device || device.cameraUrl === ""
                        color: UM.Theme.getColor("monitor_text_disabled")
                        text: catalog.i18nc("@label", "Waiting for camera…")
                    }
                    Rectangle
                    {
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.margins: UM.Theme.getSize("default_margin").width
                        visible: device && device.cameraUrl !== ""
                        color: UM.Theme.getColor("monitor_tooltip")
                        radius: UM.Theme.getSize("default_radius").width
                        width: camLabel.width + 2 * UM.Theme.getSize("narrow_margin").width
                        height: camLabel.height + UM.Theme.getSize("narrow_margin").height
                        UM.Label
                        {
                            id: camLabel
                            anchors.centerIn: parent
                            color: UM.Theme.getColor("monitor_tooltip_text")
                            font: UM.Theme.getFont("small")
                            text: catalog.i18nc("@label", "Camera · refreshes every 3 s")
                        }
                    }
                }

                // Status column
                ColumnLayout
                {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    spacing: UM.Theme.getSize("default_margin").height

                    UM.Label
                    {
                        text: device && device.activePrinter ? device.activePrinter.name : "Zortrax M200 Plus"
                        font: UM.Theme.getFont("large")
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Row
                    {
                        spacing: UM.Theme.getSize("narrow_margin").width
                        Rectangle
                        {
                            width: pillText.width + 2 * UM.Theme.getSize("narrow_margin").width
                            height: pillText.height + UM.Theme.getSize("thin_margin").height * 2
                            radius: height / 2
                            color: UM.Theme.getColor("monitor_printer_family_tag")
                            UM.Label { id: pillText; anchors.centerIn: parent; font: UM.Theme.getFont("small"); text: "M200 Plus" }
                        }
                        UM.Label
                        {
                            anchors.verticalCenter: parent.verticalCenter
                            color: UM.Theme.getColor("text_inactive")
                            text: device ? device.host : ""
                        }
                    }

                    // Error banner
                    Rectangle
                    {
                        Layout.fillWidth: true
                        visible: !reachable
                        color: UM.Theme.getColor("warning")
                        radius: UM.Theme.getSize("default_radius").width
                        implicitHeight: errText.implicitHeight + 2 * UM.Theme.getSize("default_margin").height
                        UM.Label
                        {
                            id: errText
                            anchors.fill: parent
                            anchors.margins: UM.Theme.getSize("default_margin").width
                            wrapMode: Text.Wrap
                            text: catalog.i18nc("@label", "Printer not reachable: %1").arg(device ? device.lastError : "")
                        }
                    }

                    UM.Label
                    {
                        text: stateText(state_)
                        font: UM.Theme.getFont("medium_bold")
                        color: state_ === "failsafe" ? UM.Theme.getColor("error") : UM.Theme.getColor("text")
                    }

                    // Temperatures and material
                    GridLayout
                    {
                        columns: 2
                        columnSpacing: UM.Theme.getSize("wide_margin").width
                        rowSpacing: UM.Theme.getSize("narrow_margin").height
                        Row
                        {
                            spacing: UM.Theme.getSize("narrow_margin").width
                            UM.ColorImage { width: UM.Theme.getSize("section_icon").width; height: width; source: UM.Theme.getIcon("Nozzle"); color: UM.Theme.getColor("icon") }
                            UM.Label { anchors.verticalCenter: parent.verticalCenter; text: catalog.i18nc("@label", "Nozzle %1 °C").arg(st.hotendTemperature || "–") }
                        }
                        Row
                        {
                            spacing: UM.Theme.getSize("narrow_margin").width
                            UM.ColorImage { width: UM.Theme.getSize("section_icon").width; height: width; source: UM.Theme.getIcon("Printer"); color: UM.Theme.getColor("icon") }
                            UM.Label { anchors.verticalCenter: parent.verticalCenter; text: catalog.i18nc("@label", "Bed %1 °C").arg(st.heatbedTemperature || "–") }
                        }
                        Row
                        {
                            spacing: UM.Theme.getSize("narrow_margin").width
                            UM.ColorImage { width: UM.Theme.getSize("section_icon").width; height: width; source: UM.Theme.getIcon("Spool"); color: UM.Theme.getColor("icon") }
                            UM.Label { anchors.verticalCenter: parent.verticalCenter; text: st.currentMaterial || "–" }
                        }
                        UM.Label
                        {
                            color: UM.Theme.getColor("text_inactive")
                            text: st.storageBytesFree ? catalog.i18nc("@label", "%1 GB free").arg((parseFloat(st.storageBytesFree) / 1e9).toFixed(1)) : ""
                        }
                    }

                    // Job
                    Rectangle
                    {
                        Layout.fillWidth: true
                        implicitHeight: 1
                        color: UM.Theme.getColor("lining")
                    }
                    UM.Label
                    {
                        Layout.fillWidth: true
                        elide: Text.ElideMiddle
                        font: UM.Theme.getFont("default_bold")
                        text: st.job_filename ? st.job_filename : catalog.i18nc("@label", "No active print job")
                        color: st.job_filename ? UM.Theme.getColor("text") : UM.Theme.getColor("monitor_text_disabled")
                    }
                    Row
                    {
                        visible: !!st.job_filename
                        spacing: UM.Theme.getSize("default_margin").width
                        UM.ProgressBar
                        {
                            anchors.verticalCenter: parent.verticalCenter
                            width: UM.Theme.getSize("monitor_progress_bar").width
                            value: progress / 100
                        }
                        UM.Label { text: Math.round(progress) + "%" + (st.job_estimated ? " " + catalog.i18nc("@label", "(estimated)") : "") }
                    }

                    // Controls
                    Row
                    {
                        spacing: UM.Theme.getSize("default_margin").width
                        Cura.SecondaryButton
                        {
                            text: paused ? catalog.i18nc("@action:button", "Resume") : catalog.i18nc("@action:button", "Pause")
                            enabled: reachable && (printing || paused)
                            onClicked: device.sendControl(paused ? "resume" : "pause")
                        }
                        Cura.SecondaryButton
                        {
                            text: catalog.i18nc("@action:button", "Abort")
                            enabled: reachable && (printing || paused)
                            onClicked: abortConfirm.open()
                        }
                    }
                    Row
                    {
                        spacing: UM.Theme.getSize("narrow_margin").width
                        UM.Label { anchors.verticalCenter: parent.verticalCenter; text: catalog.i18nc("@label", "Lights") ; width: 60 * screenScaleFactor }
                        Repeater
                        {
                            model: [["off", catalog.i18nc("@action:button", "Off")], ["white", catalog.i18nc("@action:button", "White")], ["dynamic", catalog.i18nc("@action:button", "Dynamic")]]
                            Cura.SecondaryButton
                            {
                                text: modelData[1]
                                enabled: reachable
                                onClicked: device.setLights(modelData[0])
                            }
                        }
                    }
                }
            }
        }

        // Files stored on the printer
        Rectangle
        {
            id: filesCard
            anchors.top: card.bottom
            anchors.topMargin: UM.Theme.getSize("default_margin").height
            anchors.horizontalCenter: parent.horizontalCenter
            width: card.width
            height: filesColumn.height + 2 * UM.Theme.getSize("default_margin").height
            color: UM.Theme.getColor("monitor_card_background")
            border.color: UM.Theme.getColor("monitor_card_border")
            border.width: UM.Theme.getSize("default_lining").width
            radius: UM.Theme.getSize("default_radius").width
            visible: !!device

            Column
            {
                id: filesColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: UM.Theme.getSize("default_margin").width
                spacing: UM.Theme.getSize("narrow_margin").height

                RowLayout
                {
                    width: parent.width
                    UM.Label
                    {
                        Layout.fillWidth: true
                        font: UM.Theme.getFont("large_bold")
                        text: catalog.i18nc("@title", "Files on this printer")
                    }
                    UM.Label
                    {
                        visible: device && device.filesLoading
                        text: catalog.i18nc("@label", "Loading…")
                        color: UM.Theme.getColor("text_medium")
                    }
                    Cura.TertiaryButton
                    {
                        text: catalog.i18nc("@action:button", "Refresh")
                        enabled: reachable && device && !device.filesLoading
                        onClicked: device.refreshFiles()
                    }
                }

                UM.Label
                {
                    visible: device && !device.filesLoading && device.printerFiles.length === 0
                    text: catalog.i18nc("@label", "No print files on the printer.")
                    color: UM.Theme.getColor("monitor_text_disabled")
                }

                ListView
                {
                    id: fileList
                    width: parent.width
                    height: Math.min(contentHeight, 6 * 36 * screenScaleFactor)
                    clip: true
                    model: device ? device.printerFiles : []
                    ScrollBar.vertical: UM.ScrollBar {}
                    delegate: Rectangle
                    {
                        width: fileList.width
                        height: 36 * screenScaleFactor
                        color: index % 2 ? "transparent" : UM.Theme.getColor("monitor_stage_background")
                        RowLayout
                        {
                            anchors.fill: parent
                            anchors.leftMargin: UM.Theme.getSize("narrow_margin").width
                            anchors.rightMargin: UM.Theme.getSize("narrow_margin").width
                            spacing: UM.Theme.getSize("default_margin").width
                            UM.Label { Layout.fillWidth: true; elide: Text.ElideMiddle; text: modelData.name }
                            UM.Label { text: modelData.modified; color: UM.Theme.getColor("text_medium") }
                            UM.Label { text: modelData.size; color: UM.Theme.getColor("text_medium"); Layout.preferredWidth: 60 * screenScaleFactor; horizontalAlignment: Text.AlignRight }
                            Cura.SecondaryButton
                            {
                                text: catalog.i18nc("@action:button", "Print")
                                enabled: reachable && !printing && !paused
                                onClicked: device.printStoredFile(modelData.name)
                            }
                            Cura.TertiaryButton
                            {
                                text: catalog.i18nc("@action:button", "Delete")
                                enabled: reachable
                                onClicked: { deleteConfirm.fileName = modelData.name; deleteConfirm.open() }
                            }
                        }
                    }
                }
            }
        }

        UM.MessageDialog
        {
            id: deleteConfirm
            property string fileName: ""
            title: catalog.i18nc("@window:title", "Delete file")
            text: catalog.i18nc("@label", "Delete %1 from the printer? This cannot be undone.").arg(fileName)
            standardButtons: Dialog.Yes | Dialog.No
            onAccepted: device.deleteStoredFile(fileName)
        }

        UM.MessageDialog
        {
            id: abortConfirm
            title: catalog.i18nc("@window:title", "Abort print")
            text: catalog.i18nc("@label", "Are you sure you want to abort the print? It cannot be resumed.")
            standardButtons: Dialog.Yes | Dialog.No
            onAccepted: device.sendControl("abort")
        }
    }
}
