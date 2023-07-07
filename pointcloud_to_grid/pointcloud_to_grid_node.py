import rclpy
from rclpy.node import Node
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import PointCloud2
from rclpy.qos import DurabilityPolicy, qos_profile_system_default
import math
import numpy as np
from pointcloud_to_grid.pointcloud_to_grid_core import GridMap, PointXY, PointXYZI
from pointcloud_to_grid.point_cloud2 import read_points


class PointcloudToGridNode(Node):
    def __init__(self):
        # Se
        super().__init__("pointcloud_to_grid_node")

        # Create occupancy grids
        self.intensity_grid = OccupancyGrid()
        self.height_grid = OccupancyGrid()

        # Create GridMap object
        self.grid_map = GridMap()

        # Read all parameters from the .yaml file
        self.declare_parameter("cell_size", 0.5)
        self.declare_parameter("position_x", -5.0)
        self.declare_parameter("position_y", 0.0)
        self.declare_parameter("length_x", 80.0)
        self.declare_parameter("length_y", 80.0)
        self.declare_parameter("cloud_in_topic", "/left_os1/os1_cloud_node/points")
        self.declare_parameter("intensity_factor", 0.2)
        self.declare_parameter("height_factor", 1.0)
        self.declare_parameter("mapi_topic_name", "/lidargrid_i")
        self.declare_parameter("maph_topic_name", "/lidargrid_h")

        # Save all the parameters to the GridMap object
        self.grid_map.cell_size         = self.get_parameter("cell_size").get_parameter_value().double_value
        self.grid_map.position_x        = self.get_parameter("position_x").get_parameter_value().double_value
        self.grid_map.position_y        = self.get_parameter("position_y").get_parameter_value().double_value
        self.grid_map.length_x          = self.get_parameter("length_x").get_parameter_value().double_value
        self.grid_map.length_y          = self.get_parameter("length_y").get_parameter_value().double_value
        self.grid_map.cloud_in_topic    = self.get_parameter("cloud_in_topic").get_parameter_value().string_value
        self.grid_map.intensity_factor  = self.get_parameter("intensity_factor").get_parameter_value().double_value
        self.grid_map.height_factor     = self.get_parameter("height_factor").get_parameter_value().double_value
        self.grid_map.mapi_topic_name   = self.get_parameter("mapi_topic_name").get_parameter_value().string_value
        self.grid_map.maph_topic_name   = self.get_parameter("maph_topic_name").get_parameter_value().string_value

        self.max_x  = (self.grid_map.length_x)/2 + self.grid_map.position_x
        self.min_x  = -(self.grid_map.length_x)/2 + self.grid_map.position_x
        self.max_y  = (self.grid_map.length_y)/2 + self.grid_map.position_y
        self.min_y  = -(self.grid_map.length_y)/2 + self.grid_map.position_y

        # Set up the Height and Intensity maps and refresh the parameters
        self.grid_map.initGrid(self.intensity_grid)
        self.grid_map.initGrid(self.height_grid)
        self.grid_map.paramRefresh()

        adjusted_policy = qos_profile_system_default
        adjusted_policy.durability = DurabilityPolicy.TRANSIENT_LOCAL

        # Set up Intensity base Grid Publisher
        self.publish_igrid = self.create_publisher(
            OccupancyGrid, self.grid_map.mapi_topic_name, adjusted_policy
        )

        # Set up Height based Grid Publisher
        self.publish_hgrid = self.create_publisher(
            OccupancyGrid, self.grid_map.maph_topic_name, adjusted_policy
        )

        # Set up PC2 Subscriber
        self.sub_pc2 = self.create_subscription(
            PointCloud2, self.grid_map.cloud_in_topic, self.pointcloud_callback, 1
        )

    def pointcloud_callback(self, msg : PointCloud2):
        # Adjust grid dimensions
        self.grid_map.length_x      = abs(self.max_x) + abs(self.min_x)
        self.grid_map.length_y      = abs(self.max_y) + abs(self.min_y)
        self.grid_map.position_x    = (self.max_x + self.min_x)/2.0
        self.grid_map.position_y    = (self.max_y + self.min_y)/2.0
        self.get_logger().error("Position X: " + str(self.grid_map.position_x))
        self.get_logger().error("Position Y: " + str(self.grid_map.position_y))

        self.grid_map.paramRefresh()
        
        # Setup output cloud
        out_cloud = self.process_point_cloud(msg)

        # Initialize grids
        self.grid_map.initGrid(self.intensity_grid)
        self.grid_map.initGrid(self.height_grid)

        # Create point vectors and fill them with values of -128
        ipoints = np.full(
            (self.grid_map.cell_num_x * self.grid_map.cell_num_y), -128, dtype=np.int8
        )
        hpoints = np.full(
            (self.grid_map.cell_num_x * self.grid_map.cell_num_y), -128, dtype=np.int8
        )

        # If statement math?
        for out_point in out_cloud:

            if (out_point.x > 0.01 or out_point.x < -0.01):

                if (out_point.x > self.grid_map.bottomright_x and out_point.x < self.grid_map.topleft_x):

                    if (out_point.y > self.grid_map.bottomright_y and out_point.y < self.grid_map.topleft_y):

                        # Get grid cell indices for the current point
                        cell = self.get_index(out_point.x, out_point.y, self.grid_map)

                        if (cell.x < self.grid_map.cell_num_x and cell.y < self.grid_map.cell_num_y):
                            ipoints[cell.y * self.grid_map.cell_num_x + cell.x] = out_point.intensity * self.grid_map.intensity_factor
                            hpoints[cell.y * self.grid_map.cell_num_x + cell.x] = out_point.z * self.grid_map.height_factor

                        else:
                            self.get_logger().error("Cell out of range: " + str(cell.x) + " - " + str(self.grid_map.cell_num_x) + " ||| " + str(cell.y) + " - " + str(self.grid_map.cell_num_y), 5)

                    else:
                        isTop : bool
                        if (out_point.y > self.grid_map.bottomright_y):
                            diff    = abs(out_point.y - self.grid_map.bottomright_y)
                            isTop   = False
                        else:
                            diff    = abs(out_point.y - self.grid_map.topleft_y)
                            isTop   = True

                        if (self.grid_map.length_y + diff > abs(self.max_y) + abs(self.min_y)):
                            if isTop:
                                self.max_y = self.max_y + diff
                            else:
                                self.min_y = self.min_y - diff
                
                else:
                    isTop : bool
                    if (out_point.x > self.grid_map.bottomright_x):
                        diff    = abs(out_point.x - self.grid_map.bottomright_x)
                        isTop   = False
                    else:
                        diff    = abs(out_point.x - self.grid_map.topleft_x)
                        isTop   = True

                    if (self.grid_map.length_x + diff > abs(self.max_x) + abs(self.min_x)):
                        if isTop:
                            self.max_x = self.max_x + diff
                        else:
                            self.min_x = self.min_x - diff


        # Adjust Grid Headers and set data
        now = self.get_clock().now().to_msg()

        self.intensity_grid.header.stamp        = now
        self.intensity_grid.header.frame_id     = msg.header.frame_id
        self.intensity_grid.info.map_load_time  = now
        self.intensity_grid.data                = ipoints.astype(int).tolist()

        self.height_grid.header.stamp           = now
        self.height_grid.header.frame_id        = msg.header.frame_id
        self.height_grid.info.map_load_time     = now
        self.height_grid.data                   = hpoints.astype(int).tolist()

        # Publish new grids
        self.publish_igrid.publish(self.intensity_grid)
        self.publish_hgrid.publish(self.height_grid)


    def get_index(self, x: float, y: float, grid_map: GridMap):
        ret     = PointXY()
        ret.x   = int(math.fabs(x - grid_map.topleft_x) / grid_map.cell_size)
        ret.y   = int(math.fabs(y - grid_map.topleft_y) / grid_map.cell_size)
        return ret

    def process_point_cloud(self, cloud_msg : PointCloud2):
        points = []

        # Read points from the PointCloud2 message
        for point_data in read_points(cloud_msg, field_names=['x', 'y', 'z', 'intensity']):
            point = PointXYZI()

            # Assign values to the PointXYZI object
            point.x = point_data[0]
            point.y = point_data[1]
            point.z = point_data[2]
            point.intensity = point_data[3]

            # Add the point to the list
            points.append(point)

        return points

def main(args=None):
    rclpy.init(args=args)
    node = PointcloudToGridNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
