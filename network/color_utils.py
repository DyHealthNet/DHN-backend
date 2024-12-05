import seaborn as sns


# functions to get appropriate background colors for plotting
def darken_hex(hex_color, factor=0.2):
    # Convert the hex color to RGB
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    # Darken the color by the factor
    r = int(r * (1 - factor))
    g = int(g * (1 - factor))
    b = int(b * (1 - factor))
    # Convert back to hex
    return f'#{r:02x}{g:02x}{b:02x}'


# functions to get appropriate colors for plotting
def rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))


# functions to darken rgb plotting for border colour of color palette
def darken_rgb(rgb, factor=0.2):
    darkened_rgb = [max(0, min(1, c - factor)) for c in rgb]
    return tuple(darkened_rgb)


def enlarge_palette(color_palette, n_colors):
    enlarged_palette = color_palette * (n_colors // len(color_palette)) + color_palette[
                                                                          :n_colors % len(color_palette)]
    return enlarged_palette


def lighten_color(hex_color, factor=0.2):
    """Lighten a hex color by a given factor (0.0 to 1.0)."""
    # Strip the '#' if present
    hex_color = hex_color.lstrip('#')
    # Convert hex to RGB
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    # Lighten each channel
    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))
    # Convert back to hex
    return f"#{r:02x}{g:02x}{b:02x}"


# Colormaps for overview page plots
COLOR_PALETTE = sns.color_palette("muted")
