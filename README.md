# strict_hdds

#### 介绍
Ensures only some optimized harddisk layouts are used.

#### 软件架构
软件架构说明


#### 安装教程

1.  xxxx
2.  xxxx
3.  xxxx

#### 使用说明

1.  xxxx
2.  xxxx
3.  xxxx

#### 参与贡献

1.  Fork 本仓库
2.  新建 Feat_xxx 分支
3.  提交代码
4.  新建 Pull Request


#### 特技

1.  使用 Readme\_XXX.md 来支持不同的语言，例如 Readme\_en.md, Readme\_zh.md
2.  Gitee 官方博客 [blog.gitee.com](https://blog.gitee.com)
3.  你可以 [https://gitee.com/explore](https://gitee.com/explore) 这个地址来了解 Gitee 上的优秀开源项目
4.  [GVP](https://gitee.com/gvp) 全称是 Gitee 最有价值开源项目，是综合评定出的优秀开源项目
5.  Gitee 官方提供的使用手册 [https://gitee.com/help](https://gitee.com/help)
6.  Gitee 封面人物是一档用来展示 Gitee 会员风采的栏目 [https://gitee.com/gitee-stars/](https://gitee.com/gitee-stars/)



https://pypi.org/project/pyfatfs/
https://github.com/isislovecruft/pyrsync/blob/master/pyrsync.py

手动解析和修改FAT文件系统中的BPB（Boot Parameter Block）。

FAT文件系统的BPB是一个4096字节的结构，其中包含了与FAT文件系统相关的各种信息，如分区的大小、FAT表的位置、每个簇的大小、OEM名称、卷标以及UUID等等。因此，你可以手动读取和修改BPB以实现更改FAT分区的UUID或LABEL。


def change_fat_uuid_and_label(partition, new_uuid=None, new_label=None):
    with open(partition, "rb+") as f:
        # 读取第一个扇区（偏移量为0）
        sector_size = 512
        buffer = f.read(sector_size)

        # 解析BPB结构体
        bpb_size = 0x3e  # FAT32中BPB的固定大小
        bpb_format = "<3s8sHBHBHHBHHLLLHHBL"
        bpb_struct = struct.Struct(bpb_format)
        bpb_values = bpb_struct.unpack_from(buffer, 0)

        # 获取原来的UUID和LABEL
        uuid_position = 0x5a  # UUID在BPB中的偏移量
        label_position = 0x47  # LABEL在BPB中的偏移量
        uuid_bytes = buffer[uuid_position:uuid_position+16]
        label_bytes = buffer[label_position:label_position+11]
        uuid = uuid_bytes.decode("utf-8").strip()
        label = label_bytes.decode("utf-8").strip()

        # 生成新的UUID和LABEL（如果未提供）
        if not new_uuid:
            new_uuid = "123e4567-e89b-12d3-a456-426655440000"
        if not new_label:
            new_label = "new_label".ljust(11).encode("utf-8")

        # 更新BPB中的UUID和LABEL
        f.seek(uuid_position)
        f.write(new_uuid.encode("utf-8").ljust(16).encode("ascii"))
        f.seek(label_position)
        f.write(new_label)

        # 刷新缓冲区
        f.flush()
        os.fsync(f.fileno())
