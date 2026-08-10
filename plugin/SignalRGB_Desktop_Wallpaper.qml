import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    anchors.fill: parent

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        Text {
            color: theme.primarytextcolor
            font.family: theme.primaryfont
            font.weight: Font.Bold
            font.pixelSize: 18
            text: "SignalRGB Desktop Wallpaper"
        }

        Text {
            color: theme.secondarytextcolor
            font.family: theme.secondaryfont
            font.pixelSize: 13
            wrapMode: Text.WordWrap
            Layout.preferredWidth: 520
            text: "A virtual lighting device that forwards a small set of glow zones over local UDP to bridge.py, which relays them to a Lively / Wallpaper Engine wallpaper running on your desktop. No physical device is paired — registration is automatic when this service is enabled."
        }

        Rectangle {
            id: scanningItem
            height: 50
            width: 360
            visible: service.controllers.length === 0
            color: theme.background2
            radius: theme.radius

            BusyIndicator {
                id: scanningIndicator
                height: 30
                anchors.verticalCenter: parent.verticalCenter
                width: parent.height
                Material.accent: "#88FFFFFF"
                running: scanningItem.visible
            }

            Text {
                anchors.left: scanningIndicator.right
                anchors.verticalCenter: parent.verticalCenter
                color: "White"
                text: "Registering virtual device…"
                font.pixelSize: 13
                font.family: theme.secondaryfont
            }
        }

        Repeater {
            model: service.controllers

            delegate: Pane {
                width: 360
                height: 64
                padding: 12

                background: Rectangle {
                    color: theme.background2
                    radius: 8
                }

                property var device: model.modelData.obj

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 2

                    Text {
                        color: theme.primarytextcolor
                        font.family: theme.primaryfont
                        font.weight: Font.Bold
                        font.pixelSize: 14
                        text: device && device.name ? device.name : "Desktop Wallpaper"
                    }
                    Text {
                        color: theme.secondarytextcolor
                        font.family: theme.secondaryfont
                        font.pixelSize: 12
                        text: "id: " + (device && device.id ? device.id : "?")
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
