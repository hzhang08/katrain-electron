"""Resolve a move on the selected ancestry and its preferred continuation."""


def node_at_move(current, number):
    if type(number) is not int or number < 0:
        raise ValueError("Enter a whole move number, starting at 0.")
    node = current
    while node.parent and node.depth > number:
        node = node.parent
    while node.depth < number and node.ordered_children:
        node = node.ordered_children[0]
    if node.depth != number:
        raise ValueError(f"This variation ends at move {node.depth}.")
    return node
