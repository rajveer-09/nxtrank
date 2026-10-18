# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""leetcode topics: LeetCode's topic list, the topics provisional tags may use

Revision ID: a3c5e7f9b104
Revises: f1b3d5e7a942
Create Date: 2026-10-18 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c5e7f9b104'
down_revision: Union[str, Sequence[str], None] = 'f1b3d5e7a942'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# LeetCode's topics as of October 2026. Official tags seen later are added automatically.
TOPICS = [
    ("array", "Array"),
    ("string", "String"),
    ("hash-table", "Hash Table"),
    ("dynamic-programming", "Dynamic Programming"),
    ("math", "Math"),
    ("sorting", "Sorting"),
    ("greedy", "Greedy"),
    ("depth-first-search", "Depth-First Search"),
    ("binary-search", "Binary Search"),
    ("database", "Database"),
    ("matrix", "Matrix"),
    ("tree", "Tree"),
    ("breadth-first-search", "Breadth-First Search"),
    ("bit-manipulation", "Bit Manipulation"),
    ("two-pointers", "Two Pointers"),
    ("prefix-sum", "Prefix Sum"),
    ("heap-priority-queue", "Heap (Priority Queue)"),
    ("simulation", "Simulation"),
    ("binary-tree", "Binary Tree"),
    ("graph", "Graph"),
    ("stack", "Stack"),
    ("counting", "Counting"),
    ("sliding-window", "Sliding Window"),
    ("design", "Design"),
    ("enumeration", "Enumeration"),
    ("backtracking", "Backtracking"),
    ("union-find", "Union Find"),
    ("linked-list", "Linked List"),
    ("number-theory", "Number Theory"),
    ("ordered-set", "Ordered Set"),
    ("monotonic-stack", "Monotonic Stack"),
    ("segment-tree", "Segment Tree"),
    ("trie", "Trie"),
    ("combinatorics", "Combinatorics"),
    ("bitmask", "Bitmask"),
    ("divide-and-conquer", "Divide and Conquer"),
    ("queue", "Queue"),
    ("recursion", "Recursion"),
    ("geometry", "Geometry"),
    ("binary-indexed-tree", "Binary Indexed Tree"),
    ("memoization", "Memoization"),
    ("hash-function", "Hash Function"),
    ("binary-search-tree", "Binary Search Tree"),
    ("shortest-path", "Shortest Path"),
    ("string-matching", "String Matching"),
    ("topological-sort", "Topological Sort"),
    ("rolling-hash", "Rolling Hash"),
    ("game-theory", "Game Theory"),
    ("interactive", "Interactive"),
    ("data-stream", "Data Stream"),
    ("monotonic-queue", "Monotonic Queue"),
    ("brainteaser", "Brainteaser"),
    ("doubly-linked-list", "Doubly Linked List"),
    ("randomized", "Randomized"),
    ("merge-sort", "Merge Sort"),
    ("counting-sort", "Counting Sort"),
    ("iterator", "Iterator"),
    ("concurrency", "Concurrency"),
    ("probability-and-statistics", "Probability and Statistics"),
    ("quickselect", "Quickselect"),
    ("suffix-array", "Suffix Array"),
    ("line-sweep", "Line Sweep"),
    ("minimum-spanning-tree", "Minimum Spanning Tree"),
    ("bucket-sort", "Bucket Sort"),
    ("shell", "Shell"),
    ("reservoir-sampling", "Reservoir Sampling"),
    ("strongly-connected-component", "Strongly Connected Component"),
    ("eulerian-circuit", "Eulerian Circuit"),
    ("radix-sort", "Radix Sort"),
    ("rejection-sampling", "Rejection Sampling"),
    ("biconnected-component", "Biconnected Component"),
]


def upgrade() -> None:
    """Upgrade schema."""
    table = op.create_table(
        'leetcode_topics',
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('slug', name=op.f('pk_leetcode_topics')),
    )
    op.bulk_insert(table, [{"slug": slug, "name": name} for slug, name in TOPICS])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('leetcode_topics')
