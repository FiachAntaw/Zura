import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import UM 1.5 as UM

// Monitor tab for a Zortrax printer: camera snapshot, status and controls.
Item {
    id: root
    property var device: OutputDevice
    property var st: device ? device.zortraxStatus : ({})
    anchors.fill: parent

    Rectangle { anchors.fill: parent; color: UM.Theme.getColor("main_background") }

    RowLayout {
        anchors.fill: parent
        anchors.margins: UM.Theme.getSize("default_margin").width
        spacing: UM.Theme.getSize("default_margin").width

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "black"
            Image {
                anchors.fill: parent
                fillMode: Image.PreserveAspectFit
                cache: false
                source: device ? device.cameraUrl : ""
            }
            UM.Label {
                anchors.centerIn: parent
                visible: !device || device.cameraUrl === ""
                color: "white"
                text: "Waiting for camera snapshot…"
            }
        }

        ColumnLayout {
            Layout.preferredWidth: 320
            Layout.fillHeight: true
            spacing: UM.Theme.getSize("default_lining").height * 6

            UM.Label { text: device ? device.name : ""; font: UM.Theme.getFont("large_bold") }
            UM.Label { text: "Address: " + (device ? device.host : "") }
            UM.Label { visible: device && device.lastError !== ""; color: UM.Theme.getColor("error"); wrapMode: Text.Wrap; Layout.fillWidth: true
                       text: device ? "Not reachable: " + device.lastError : "" }
            UM.Label { text: "State: " + (st.printerStatus || "unknown") }
            UM.Label { text: "Hotend: " + (st.hotendTemperature || "–") + " °C    Bed: " + (st.heatbedTemperature || "–") + " °C" }
            UM.Label { text: "Material: " + (st.currentMaterial || "–") }
            UM.Label { visible: !!st.job_filename; text: "Job: " + (st.job_filename || "") }
            ProgressBar {
                Layout.fillWidth: true
                visible: !!st.job_progress
                from: 0; to: 100
                value: st.job_progress ? parseFloat(st.job_progress) : 0
            }
            UM.Label { visible: !!st.job_progress; text: (st.job_progress || "0") + " %" }
            UM.Label { text: "Storage free: " + (st.storageBytesFree ? (parseFloat(st.storageBytesFree) / 1e9).toFixed(2) + " GB" : "–") }

            RowLayout {
                Button { text: "Pause"; onClicked: device.sendControl("pause") }
                Button { text: "Resume"; onClicked: device.sendControl("resume") }
                Button { text: "Abort"; onClicked: abortConfirm.open() }
            }
            RowLayout {
                UM.Label { text: "Lights:" }
                Button { text: "Off"; onClicked: device.setLights("off") }
                Button { text: "White"; onClicked: device.setLights("white") }
                Button { text: "Dynamic"; onClicked: device.setLights("dynamic") }
            }
            Item { Layout.fillHeight: true }
        }
    }

    Dialog {
        id: abortConfirm
        anchors.centerIn: parent
        title: "Abort print?"
        modal: true
        standardButtons: Dialog.Yes | Dialog.No
        onAccepted: device.sendControl("abort")
        UM.Label { text: "The current print will be stopped and cannot be resumed." }
    }
}
