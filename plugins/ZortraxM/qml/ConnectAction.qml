import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import UM 1.5 as UM
import Cura 1.0 as Cura

Cura.MachineAction {
    id: base
    anchors.fill: parent
    property var action: manager

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: UM.Theme.getSize("default_margin").width
        spacing: UM.Theme.getSize("default_margin").height

        UM.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: "Choose your Zortrax printer on the local network, or type its IP address. Cura will then show its status and camera in the Monitor tab and can send prints to it."
        }
        UM.Label { text: "Current printer address: " + (action.host || "not set") }

        RowLayout {
            Button { text: "Search network"; onClicked: action.refresh() }
        }
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.preferredHeight: 160
            clip: true
            model: action.discovered
            delegate: ItemDelegate {
                width: list.width
                text: modelData.serial + "  (" + modelData.host + ")"
                onClicked: { address.text = modelData.host }
            }
            UM.Label { anchors.centerIn: parent; visible: list.count === 0; text: "No printers found yet." }
        }
        RowLayout {
            TextField { id: address; placeholderText: "192.168.1.159"; text: action.host; Layout.preferredWidth: 220 }
            Button { text: "Connect"; enabled: address.text.length > 6; onClicked: action.setHost(address.text) }
            Button { text: "Disconnect"; enabled: action.host !== ""; onClicked: action.setHost("") }
        }
        Item { Layout.fillHeight: true }
    }
}
