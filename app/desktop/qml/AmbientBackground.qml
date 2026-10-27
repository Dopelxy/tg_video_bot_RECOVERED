import QtQuick

Canvas {
    objectName: "ambientBackground"
    // This separate source contains no foreground controls or text.
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        ctx.fillStyle = Theme.background
        ctx.fillRect(0, 0, width, height)
        const lights = [
            [width * 0.70, -height * 0.05, width * 0.65, "rgba(199,179,138,0.15)"],
            [-width * 0.05, height * 0.66, width * 0.54, "rgba(101,203,184,0.13)"],
            [width * 0.98, height * 1.05, width * 0.60, "rgba(98,110,153,0.14)"]
        ]
        for (let light of lights) {
            const gradient = ctx.createRadialGradient(light[0], light[1], 0, light[0], light[1], light[2])
            gradient.addColorStop(0, light[3])
            gradient.addColorStop(1, "rgba(13,16,21,0)")
            ctx.fillStyle = gradient
            ctx.fillRect(0, 0, width, height)
        }
    }
}
