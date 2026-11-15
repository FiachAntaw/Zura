// "Connect via Network" page for Zortrax printers (Preferences > Printers).
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import UM 1.5 as UM
import Cura 1.0 as Cura

Cura.MachineAction
{
    id: base
    anchors.fill: parent
    property var action: manager
    property string host: action ? action.host : ""
    property string selectedHost: ""

    UM.I18nCatalog { id: catalog; name: "cura" }

    ColumnLayout
    {
        anchors.fill: parent
        spacing: UM.Theme.getSize("default_margin").height

        UM.Label
        {
            text: catalog.i18nc("@title:window", "Connect to Zortrax Printer")
            font: UM.Theme.getFont("large_bold")
        }
        UM.Label
        {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: catalog.i18nc("@label", "Make sure the printer is switched on and on the same network as this computer. Select it from the list, or enter its IP address (shown on the printer under Settings > Network).")
        }

        // Current connection
        Rectangle
        {
            Layout.fillWidth: true
            implicitHeight: currentRow.implicitHeight + 2 * UM.Theme.getSize("default_margin").height
            color: base.host ? UM.Theme.getColor("monitor_card_hover") : UM.Theme.getColor("main_background")
            border.color: UM.Theme.getColor("lining")
            border.width: UM.Theme.getSize("default_lining").width
            radius: UM.Theme.getSize("default_radius").width
            RowLayout
            {
                id: currentRow
                anchors.fill: parent
                anchors.margins: UM.Theme.getSize("default_margin").width
                UM.ColorImage
                {
                    Layout.preferredWidth: UM.Theme.getSize("section_icon").width
                    Layout.preferredHeight: UM.Theme.getSize("section_icon").height
                    source: base.host ? UM.Theme.getIcon("CheckCircle") : UM.Theme.getIcon("Information")
                    color: base.host ? UM.Theme.getColor("success") : UM.Theme.getColor("icon")
                }
                UM.Label
                {
                    Layout.fillWidth: true
                    text: base.host ? catalog.i18nc("@label", "Connected to %1").arg(base.host) : catalog.i18nc("@label", "Not connected to a printer")
                }
                Cura.SecondaryButton
                {
                    visible: base.host !== ""
                    text: catalog.i18nc("@action:button", "Disconnect")
                    onClicked: action.setHost("")
                }
            }
        }

        RowLayout
        {
            Layout.fillWidth: true
            UM.Label { text: catalog.i18nc("@label", "Printers on your network"); font: UM.Theme.getFont("default_bold"); Layout.fillWidth: true }
            Cura.SecondaryButton
            {
                text: catalog.i18nc("@action:button", "Refresh")
                onClicked: action.refresh()
            }
        }

        Rectangle
        {
            Layout.fillWidth: true
            Layout.preferredHeight: 150 * screenScaleFactor
            color: UM.Theme.getColor("main_background")
            border.color: UM.Theme.getColor("lining")
            border.width: UM.Theme.getSize("default_lining").width
            radius: UM.Theme.getSize("default_radius").width

            ListView
            {
                id: list
                anchors.fill: parent
                anchors.margins: UM.Theme.getSize("default_lining").width
                clip: true
                model: action ? action.discovered : []
                ScrollBar.vertical: UM.ScrollBar {}
                delegate: Rectangle
                {
                    width: list.width
                    height: rowLabel.height + 2 * UM.Theme.getSize("default_margin").height
                    color: base.selectedHost === modelData.host ? UM.Theme.getColor("background_3") : (mouse.containsMouse ? UM.Theme.getColor("monitor_card_hover") : "transparent")
                    RowLayout
                    {
                        anchors.fill: parent
                        anchors.leftMargin: UM.Theme.getSize("default_margin").width
                        anchors.rightMargin: UM.Theme.getSize("default_margin").width
                        UM.ColorImage
                        {
                            Layout.preferredWidth: UM.Theme.getSize("section_icon").width
                            Layout.preferredHeight: UM.Theme.getSize("section_icon").height
                            source: UM.Theme.getIcon("Printer"); color: UM.Theme.getColor("icon")
                        }
                        UM.Label { id: rowLabel; text: "Zortrax " + modelData.serial; Layout.fillWidth: true }
                        UM.Label { text: modelData.host; color: UM.Theme.getColor("text_inactive") }
                    }
                    MouseArea
                    {
                        id: mouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: { base.selectedHost = modelData.host; address.text = modelData.host }
                    }
                }
                UM.Label
                {
                    anchors.centerIn: parent
                    visible: list.count === 0
                    color: UM.Theme.getColor("text_inactive")
                    text: catalog.i18nc("@label", "No Zortrax printers found. Try Refresh, or enter the IP address below.")
                }
            }
        }

        RowLayout
        {
            spacing: UM.Theme.getSize("default_margin").width
            UM.Label { text: catalog.i18nc("@label", "IP address") }
            Cura.TextField
            {
                id: address
                Layout.preferredWidth: 200 * screenScaleFactor
                placeholderText: "192.168.1.100"
                text: base.host
            }
            Cura.PrimaryButton
            {
                text: catalog.i18nc("@action:button", "Connect")
                enabled: /^\d{1,3}(\.\d{1,3}){3}$/.test(address.text.trim())
                onClicked: action.setHost(address.text.trim())
            }
        }
        Item { Layout.fillHeight: true }
    }
}
