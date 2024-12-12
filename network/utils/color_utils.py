import numpy as np
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


def hsl_to_hex(hue, saturation, lightness):
    return rgb_to_hex(hsl_to_rgb(hue, saturation, lightness))


def hsl_to_rgb(hue, saturation, lightness):
    c = (1 - abs(2 * lightness - 1)) * saturation
    x = c * (1 - abs((hue / 60) % 2 - 1))
    m = lightness - c / 2
    if 0 <= hue < 60:
        r, g, b = c, x, 0
    elif 60 <= hue < 120:
        r, g, b = x, c, 0
    elif 120 <= hue < 180:
        r, g, b = 0, c, x
    elif 180 <= hue < 240:
        r, g, b = 0, x, c
    elif 240 <= hue < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return r + m, g + m, b + m


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


def define_context_color(base_hue=None):
    """
    Define a random color for each context that aligns with the theme colors
    :return: dict with lightVariant and darkVariant colors for each context
    """
    light_saturation = 0.44
    light_lightness = 0.755

    dark_saturation = 0.239
    dark_lightness = 0.418

    # get random int between 0 and 360
    if base_hue is None:
        random_vue = np.random.randint(0, 360)
    else:
        random_vue = base_hue

    base_color = hsl_to_hex(random_vue, 1, 0.5)
    light_variant = hsl_to_hex(random_vue, light_saturation, light_lightness)
    dark_variant = hsl_to_hex(random_vue, dark_saturation, dark_lightness)
    return {'color': base_color, 'lightVariant': light_variant, 'darkVariant': dark_variant}


# Colormaps for overview page plots
COLOR_PALETTE = sns.color_palette("muted")
