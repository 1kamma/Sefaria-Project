# -*- coding: utf-8 -*-

from sefaria.model import *


"""
                                                    IN PROCESS & UNTESTED


To get the existing schema nodes to pass into these functions, easiest is likely:
Ref("...").index_node


Todo:
    Clean system from old refs:
        links to commentary
        transx reqs
        elastic search
        varnish
"""

def insert_last_child(new_node, parent_node):
    return attach_branch(new_node, parent_node, len(parent_node.children))

def insert_first_child(new_node, parent_node):
    return attach_branch(new_node, parent_node, 0)

def attach_branch(new_node, parent_node, place=0):
    #//todo: mark for commentary refactor?
    """
    :param new_node: A schema node tree to attach
    :param parent_node: The parent to attach it to
    :param place: The index of the child before which to insert, so place=0 inserts at the front of the list, and place=len(parent_node.children) inserts at the end
    :return:
    """
    assert isinstance(new_node, SchemaNode)
    assert isinstance(parent_node, SchemaNode)
    assert place <= len(parent_node.children)

    index = parent_node.index

    # Add node to versions & commentary versions
    vs = [v for v in index.versionSet()]
    vsc = [v for v in library.get_commentary_versions_on_book(index.title)]
    for v in vs + vsc:
        pc = v.content_node(parent_node)
        pc[new_node.key] = new_node.create_skeleton()
        v.save()

    # Update Index schema and save
    parent_node.children.insert(place, new_node)
    new_node.parent = parent_node
    index.save()

    # Refresh VersionState
    refresh_version_state(index.title)


def remove_branch(node):
    #//todo: mark for commentary refactor?
    """
    This will delete any text in `node`
    :param node: SchemaNode to remove
    :return:
    """
    assert isinstance(node, SchemaNode)
    parent = node.parent
    assert parent
    index = node.index

    node.ref().linkset().delete()
    # todo: commentary linkset

    vs = [v for v in index.versionSet()]
    vsc = [v for v in library.get_commentary_versions_on_book(index.title)]
    for v in vs + vsc:
        assert isinstance(v, Version)
        pc = v.content_node(parent)
        del pc[node.key]
        v.save()

    parent.children = [n for n in parent.children if n.key != node.key]
    index.save()

    refresh_version_state(index.title)


def reorder_children(parent_node, new_order):
    """
    :param parent_node:
    :param new_order: List of child keys, in their new order
    :return:
    """
    # With this one, we can get away with just an Index change
    assert isinstance(parent_node, SchemaNode)
    child_dict = {n.key: n for n in parent_node.children}
    assert set(child_dict.keys()) == set(new_order)
    parent_node.children = [child_dict[k] for k in new_order]
    parent_node.index.save()


def change_parent(node, new_parent, place=0):
    #//todo: mark for commentary refactor?
    """
    :param node:
    :param new_parent:
    :param place: The index of the child before which to insert, so place=0 inserts at the front of the list, and place=len(parent_node.children) inserts at the end
    :return:
    """
    assert isinstance(node, SchemaNode)
    assert isinstance(new_parent, SchemaNode)
    assert place <= len(new_parent.children)
    old_parent = node.parent
    index = new_parent.index

    old_normal_form = node.ref().normal()
    linkset = [l for l in node.ref().linkset()]

    vs = [v for v in index.versionSet()]
    vsc = [v for v in library.get_commentary_versions_on_book(index.title)]
    for v in vs + vsc:
        assert isinstance(v, Version)
        old_parent_content = v.content_node(old_parent)
        content = old_parent_content.pop(node.key)
        new_parent_content = v.content_node(new_parent)
        new_parent_content[node.key] = content
        v.save()

    old_parent.children = [n for n in old_parent.children if n.key != node.key]
    new_parent.children.insert(place, node)
    node.parent = new_parent
    new_normal_form = node.ref().normal()
    index.save()

    for link in linkset:
        link.refs = [ref.replace(old_normal_form, new_normal_form) for ref in link.refs]
        link.save()
    # todo: commentary linkset

    refresh_version_state(index.title)


def refresh_version_state(base_title):
    #//todo: mark for commentary refactor?
    """
    VersionState is *not* altered on Index save.  It is only created on Index creation.

    VersionState is *not* automatically updated on Version save.
    The VersionState update on version save happens in texts_api().

    VersionState.refresh() assumes the structure of content has not changed.
    To regenerate VersionState, we save the flags, delete the old one, and regenerate a new one.

    """
    vtitles = library.get_commentary_version_titles_on_book(base_title) + [base_title]
    for title in vtitles:
        vs = VersionState(title)
        flags = vs.flags
        vs.delete()
        VersionState(title, {"flags": flags})