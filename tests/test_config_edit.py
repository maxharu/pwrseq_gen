"""節點清單編輯操作：命名、批次刪除、重排後的索引換算。

這些是從 `gui/app.py` 抽出來的索引算術。`remap_index_after_move` 原本是 app.py 裡的
staticmethod，純歸純、但一行測試都沒有——而它算錯的話，拖曳節點之後「目前選取的是哪一個」
就會指到錯的那一筆。
"""
import pytest

from core.config_edit import (
    delete_indices,
    move_item,
    next_rail_name,
    remap_index_after_move,
)


class TestNextRailName:
    def test_counts_from_the_list_length(self):
        assert next_rail_name(["SIG_1", "SIG_2"]) == "SIG_3"

    def test_skips_names_already_taken(self):
        """名稱被改過時，`len + 1` 可能剛好撞號，必須往後找。"""
        assert next_rail_name(["A", "B", "SIG_3"]) == "SIG_4"
        assert next_rail_name(["SIG_3", "SIG_4", "SIG_5"]) == "SIG_6"

    def test_empty_list(self):
        assert next_rail_name([]) == "SIG_1"

    def test_never_collides(self):
        names = ["SIG_1", "SIG_2", "SIG_3", "SIG_4", "SIG_5"]
        for _ in range(20):
            new = next_rail_name(names)
            assert new not in names
            names.append(new)


class TestDeleteIndices:
    def test_deletes_the_intended_items(self):
        items = ["a", "b", "c", "d", "e"]
        delete_indices(items, [1, 3])
        assert items == ["a", "c", "e"]

    def test_order_of_the_input_does_not_matter(self):
        """呼叫端給的順序不該影響結果——內部一律由大到小刪。"""
        a, b = ["a", "b", "c", "d"], ["a", "b", "c", "d"]
        delete_indices(a, [0, 2])
        delete_indices(b, [2, 0])
        assert a == b == ["b", "d"]

    def test_returns_removed_indices_largest_first(self):
        assert delete_indices(["a", "b", "c", "d"], [0, 2]) == [2, 0]

    def test_duplicates_are_collapsed(self):
        items = ["a", "b", "c"]
        assert delete_indices(items, [1, 1, 1]) == [1]
        assert items == ["a", "c"]

    def test_out_of_range_indices_are_ignored(self):
        items = ["a", "b"]
        assert delete_indices(items, [5, -1, 0]) == [0]
        assert items == ["b"]

    def test_deleting_everything(self):
        items = ["a", "b", "c"]
        delete_indices(items, range(3))
        assert items == []


class TestMoveItem:
    @pytest.mark.parametrize("a,b,want", [
        (0, 2, ["b", "c", "a", "d"]),
        (2, 0, ["c", "a", "b", "d"]),
        (0, 3, ["b", "c", "d", "a"]),
        (3, 0, ["d", "a", "b", "c"]),
    ])
    def test_moves(self, a, b, want):
        items = ["a", "b", "c", "d"]
        assert move_item(items, a, b)
        assert items == want

    @pytest.mark.parametrize("a,b", [(1, 1), (-1, 0), (0, 9), (9, 0)])
    def test_no_op_and_out_of_range_are_rejected(self, a, b):
        items = ["a", "b", "c"]
        assert move_item(items, a, b) is False
        assert items == ["a", "b", "c"]


class TestRemapIndexAfterMove:
    """重排後游標的新位置。

    用「真的去搬一次清單，再找出該元素的新位置」當 oracle，而不是重寫一遍同樣的算術
    ——否則測試只是把實作抄一次，錯一起錯。
    """

    @pytest.mark.parametrize("n", [1, 2, 3, 5, 6])
    def test_matches_an_actual_list_move(self, n):
        for from_idx in range(n):
            for to_idx in range(n):
                if from_idx == to_idx:
                    continue
                items = list(range(n))
                move_item(items, from_idx, to_idx)
                for idx in range(n):
                    assert remap_index_after_move(idx, from_idx, to_idx) == items.index(idx), (
                        f"n={n} 把 {from_idx} 移到 {to_idx} 之後，原本的 {idx} 位置算錯"
                    )

    def test_none_stays_none(self):
        assert remap_index_after_move(None, 0, 2) is None

    def test_the_moved_item_follows_the_move(self):
        assert remap_index_after_move(0, 0, 3) == 3
        assert remap_index_after_move(3, 3, 0) == 0

    def test_items_outside_the_moved_range_are_untouched(self):
        assert remap_index_after_move(5, 0, 2) == 5
        assert remap_index_after_move(0, 2, 4) == 0
